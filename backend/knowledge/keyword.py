# -*- coding: utf-8 -*-
"""Keyword retrieval with a confidence score.

Deterministic and offline. Its job is not to be clever but to be **honest about how
well it matched**: the confidence it returns is what the escalation rules use to
decide between answering and handing over, so an inflated score would turn "I do not
know" into a confident wrong answer.

Facts are returned as a structured array, never as one prose string. The customer app
builds product cards from the individual entries, and the reply composer needs to
quote them separately.
"""
from __future__ import annotations

import re
from typing import Optional

from ..domain.detection import KnowledgeMatch, RetrievalResult
from ..domain.enums import Intent, KnowledgeField, Product
from .loader import FIELD_LABELS, KnowledgeBase

# Which fields answer which question. A question routed to a field that exists is
# well grounded even if few words overlap, which is why confidence is not simply a
# word-overlap count.
INTENT_FIELDS: dict[Intent, tuple[KnowledgeField, ...]] = {
    Intent.PRICE: (KnowledgeField.PREMIUM, KnowledgeField.DEDUCTIBLE),
    Intent.COVERAGE: (KnowledgeField.COVERAGE, KnowledgeField.LIMITS),
    Intent.ELIGIBILITY: (KnowledgeField.ELIGIBILITY,),
    Intent.CLAIMS: (KnowledgeField.CLAIMS,),
    Intent.WAITING_PERIOD: (KnowledgeField.WAITING_PERIOD,),
    Intent.PAYMENT: (KnowledgeField.PAYMENT,),
    Intent.APPLICATION: (KnowledgeField.PREMIUM, KnowledgeField.ELIGIBILITY),
    Intent.COMPARISON: (KnowledgeField.POSITIONING, KnowledgeField.PREMIUM),
    Intent.FAMILY_NEED: (
        KnowledgeField.POSITIONING, KnowledgeField.COVERAGE, KnowledgeField.PREMIUM,
    ),
    Intent.CORPORATE_NEED: (
        KnowledgeField.POSITIONING, KnowledgeField.PREMIUM, KnowledgeField.ELIGIBILITY,
    ),
    Intent.UNDERWRITING: (KnowledgeField.ELIGIBILITY, KnowledgeField.EXCLUSIONS),
}

_STOPWORDS = frozenset({
    "the", "a", "an", "is", "are", "i", "we", "my", "our", "me", "us",
    "to", "of", "for", "and", "or", "in", "on", "at", "with", "how",
    "what", "does", "do", "can", "could", "would", "about", "please",
    "hi", "hello", "yes", "no", "that", "this", "it", "be", "will",
})

# Two content words must overlap before an FAQ entry is volunteered. One is noise.
_FAQ_MIN_OVERLAP = 2


def _tokenise(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if token not in _STOPWORDS and len(token) > 1
    }


class KeywordRetriever:
    def __init__(self, kb: KnowledgeBase) -> None:
        self.kb = kb

    def retrieve(
        self,
        query: str,
        product: Product = Product.UNKNOWN,
        intent: Intent = Intent.GENERIC,
    ) -> RetrievalResult:
        if product is Product.UNKNOWN or self.kb.product(product) is None:
            return self._overview()

        query_tokens = _tokenise(query)
        preferred = INTENT_FIELDS.get(intent, (KnowledgeField.POSITIONING,))
        matched_tokens: set[str] = set()
        facts: list[str] = []
        matches: list[KnowledgeMatch] = []

        def note(field: KnowledgeField, text: str) -> int:
            # The field's label is searchable too: the intent router already pointed
            # the question here, so a label match is a real hit rather than a
            # coincidence.
            overlap = query_tokens & _tokenise(f"{FIELD_LABELS[field]} {text}")
            matched_tokens.update(overlap)
            return len(overlap)

        # Positioning always leads, so every reply is anchored to what the plan is.
        positioning = self.kb.field(product, KnowledgeField.POSITIONING)
        facts.append(f"{self.kb.name(product)}: {positioning}")

        for field in preferred:
            if field is KnowledgeField.POSITIONING:
                continue
            text = self.kb.field(product, field)
            if text is None:
                continue
            facts.append(f"{FIELD_LABELS[field]}: {text}")
            matches.append(
                KnowledgeMatch(product.value, field.value, text, note(field, text))
            )

        for field in KnowledgeField:
            if field in preferred or field is KnowledgeField.POSITIONING:
                continue
            text = self.kb.field(product, field)
            if text is None:
                continue
            score = note(field, text)
            if score > 0:
                matches.append(
                    KnowledgeMatch(product.value, field.value, text, score)
                )

        matched_tokens |= query_tokens & _tokenise(
            f"{self.kb.name(product)} {' '.join(self.kb.keywords(product))}"
        )

        for item in self.kb.faq(product):
            if len(query_tokens & _tokenise(item["q"])) >= _FAQ_MIN_OVERLAP:
                facts.append(f"FAQ — {item['q']} {item['a']}")
                matched_tokens.add("faq")

        matches.sort(key=lambda match: match.score, reverse=True)
        answerable = [
            field for field in preferred
            if field is not KnowledgeField.POSITIONING
            and self.kb.field(product, field) is not None
        ]
        return RetrievalResult(
            facts=facts,
            matches=matches[:5],
            confidence=self._confidence(len(matched_tokens), intent, answerable),
            product=product,
        )

    @staticmethod
    def _confidence(
        matched_tokens: int, intent: Intent, answerable: list[KnowledgeField]
    ) -> float:
        """How well grounded the answer is.

        The dominant factor is whether an authoritative field exists for the
        question, not how many words happened to overlap: a one-word question about
        a field the knowledge base answers fully is well grounded, and treating it as
        weak would escalate work a person did not need to do. Confidence drops only
        when nothing can support the answer at all.
        """
        if intent is Intent.GENERIC:
            return 0.9
        if answerable:
            if matched_tokens >= 3:
                return 0.95
            if matched_tokens == 2:
                return 0.9
            return 0.85
        if matched_tokens >= 2:
            return 0.7
        return 0.3

    def _overview(self) -> RetrievalResult:
        return RetrievalResult(
            facts=[f"Here are the {self.kb.company} plans:"] + self.kb.overview(),
            matches=[],
            confidence=0.9,
            product=Product.UNKNOWN,
        )
