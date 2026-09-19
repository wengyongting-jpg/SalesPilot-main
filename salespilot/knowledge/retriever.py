# -*- coding: utf-8 -*-
"""Knowledge retriever (rule-based RAG placeholder).

Responsibilities (spec sections 6/7 Knowledge Base & RAG):
- Every factual product answer must be grounded in the knowledge base; no
  invented product information.
- Retrieval considers both customer intent and the detected product.
- When confidence is insufficient, the upper layer escalates instead of
  guessing.

This class can later be replaced with an embeddings + vector-database
implementation without changing the interface.
"""
import json
import re
from functools import lru_cache
from typing import Optional

from .. import config
from ..models import (
    Intent,
    KnowledgeMatch,
    Product,
    RetrievalResult,
)

# Intent -> preferred knowledge-base fields
INTENT_FIELDS: dict[Intent, tuple[str, ...]] = {
    Intent.PRICE: ("premium", "deductible"),
    Intent.COVERAGE: ("coverage", "limits"),
    Intent.ELIGIBILITY: ("eligibility",),
    Intent.CLAIMS: ("claims",),
    Intent.WAITING_PERIOD: ("waiting_period",),
    Intent.PAYMENT: ("payment",),
    Intent.APPLICATION: ("premium", "eligibility"),
    Intent.COMPARISON: ("positioning", "premium"),
    Intent.FAMILY_NEED: ("positioning", "coverage", "premium"),
    Intent.CORPORATE_NEED: ("positioning", "premium", "eligibility"),
}

FIELD_LABELS = {
    "positioning": "Overview",
    "target_customer": "Target customer",
    "eligibility": "Eligibility",
    "coverage": "Coverage",
    "premium": "Indicative premium",
    "deductible": "Deductible / co-payment",
    "limits": "Coverage limit",
    "waiting_period": "Waiting period",
    "exclusions": "Exclusions",
    "claims": "Claims process",
    "payment": "Payment",
    "renewal": "Renewal",
}

_STOPWORDS = {
    "the", "a", "an", "is", "are", "i", "we", "my", "our", "me", "us",
    "to", "of", "for", "and", "or", "in", "on", "at", "with", "how",
    "what", "does", "do", "can", "could", "would", "about", "please",
    "hi", "hello", "yes", "no", "that", "this", "it", "be", "will",
}


def _tokenize(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if token not in _STOPWORDS and len(token) > 1
    }


@lru_cache(maxsize=1)
def load_knowledge_base(kb_path: Optional[str] = None) -> dict:
    path = kb_path or str(config.KB_PATH)
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


class KnowledgeRetriever:
    def __init__(self, kb: Optional[dict] = None):
        self.kb = kb or load_knowledge_base()
        self.products = {p["id"]: p for p in self.kb["products"]}

    # ---- Public API -----------------------------------------------------

    def retrieve(
        self,
        query: str,
        product: Product = Product.UNKNOWN,
        intent: Intent = Intent.GENERIC,
    ) -> RetrievalResult:
        # No specific product: return the approved four-plan overview
        if product == Product.UNKNOWN:
            return self._product_overview(intent, query)

        product_data = self.products[product.value]
        query_tokens = _tokenize(query)
        preferred = INTENT_FIELDS.get(intent, ("positioning",))

        facts: list[str] = []
        matches: list[KnowledgeMatch] = []
        matched_tokens: set[str] = set()

        def _hit(field_name: str, text: str) -> int:
            # The field's semantic label (e.g. premium / coverage) is also
            # searchable: the intent router already pointed the question at
            # this field, so a label match counts as a real hit.
            label = FIELD_LABELS.get(field_name, field_name)
            overlap_tokens = query_tokens & _tokenize(f"{label} {text}")
            matched_tokens.update(overlap_tokens)
            return len(overlap_tokens)

        # 1) Always include positioning so the reply is grounded
        facts.append(f"{product_data['name']}: {product_data['positioning']}")

        # 2) Preferred fields for the intent (approved facts, served directly)
        for field_name in preferred:
            if field_name in product_data and field_name != "positioning":
                text = product_data[field_name]
                facts.append(f"{FIELD_LABELS.get(field_name, field_name)}: {text}")
                score = _hit(field_name, text)
                matches.append(KnowledgeMatch(product.value, field_name, text, score))

        # 3) Other fields most related to the customer's wording (dynamic fill)
        for field_name, text in product_data.items():
            if field_name in ("id", "name", "keywords", "faq",
                              "escalation_rules") or field_name in preferred:
                continue
            score = _hit(field_name, str(text))
            if score > 0:
                matches.append(
                    KnowledgeMatch(product.value, field_name, str(text), score)
                )

        # 4) Product name / keyword hits (e.g. "Essential", "Plus")
        matched_tokens |= query_tokens & _tokenize(
            product_data["name"] + " " + " ".join(product_data.get("keywords", []))
        )

        # 5) FAQ hits (require >= 2 content-word overlaps to avoid one-word false hits)
        for item in product_data.get("faq", []):
            if len(query_tokens & _tokenize(item["q"])) >= 2:
                facts.append(f"FAQ - {item['q']} {item['a']}")
                matched_tokens.add("faq")

        matches.sort(key=lambda m: m.score, reverse=True)
        preferred_existing = [
            f for f in preferred if f in product_data and f != "positioning"
        ]
        confidence = self._confidence(len(matched_tokens), intent, preferred_existing)
        return RetrievalResult(
            facts=facts,
            matches=matches[:5],
            confidence=confidence,
            product=product,
        )

    def plan_one_liners(self) -> list[str]:
        return [
            f"- {p['name']}: {p['positioning']} {p['premium']}"
            for p in self.kb["products"]
        ]

    # ---- Internals ------------------------------------------------------

    @staticmethod
    def _confidence(
        matched_tokens: int, intent: Intent, preferred_fields: list[str]
    ) -> float:
        # Overview answers come from approved static content
        if intent == Intent.GENERIC:
            return 0.9
        # Intent routed to authoritative fields that exist in the KB: the
        # answer is well grounded; more lexical hits raise confidence.
        # Only escalate when no field can support the answer at all.
        if preferred_fields:
            if matched_tokens >= 3:
                return 0.95
            if matched_tokens == 2:
                return 0.9
            return 0.85
        if matched_tokens >= 2:
            return 0.7
        return 0.3

    def _product_overview(self, intent: Intent, query: str) -> RetrievalResult:
        facts = ["Here are the CareSure plans:"] + self.plan_one_liners()
        return RetrievalResult(
            facts=facts,
            matches=[],
            confidence=0.9,
            product=Product.UNKNOWN,
        )
