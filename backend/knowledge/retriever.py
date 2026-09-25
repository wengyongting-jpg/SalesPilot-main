# -*- coding: utf-8 -*-
"""Knowledge retriever: keyword-matched grounding for product facts.

Every factual product answer must be grounded in the knowledge base; nothing
here invents product information. Retrieval considers both the detected intent
and the detected product. When confidence is insufficient, the caller
escalates instead of guessing (`backend.kernel.hitl` reads `RetrievalResult.
confidence`, not this module — retrieval only reports how well it did).

Ported from `salespilot/knowledge/retriever.py`, retargeted to
`backend.domain.enums` and `backend.domain.detection`.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Optional

from .. import config
from ..domain.detection import KnowledgeMatch, RetrievalResult
from ..domain.enums import Intent, Product

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

# Which intents get a field-specific product overview rather than the general
# name/positioning/price one. Deliberately a subset of INTENT_FIELDS's own
# keys, not all of them: an intent whose preferred field is already
# "positioning" (COMPARISON, FAMILY_NEED, CORPORATE_NEED) or "premium"
# (APPLICATION) is already well served by the general overview, and dropping
# the price to show positioning alone there would be a regression, not an
# improvement.
#
# Exported (not module-private) because `services.conversation` also reads it:
# an advice-style question in this set that names no product in the current
# message ("my father is 90, any advice?") should survey every plan's own
# field rather than silently narrow to whatever product extraction inferred
# from unrelated wording - there is nothing named to answer about specifically.
PRODUCT_SURVEY_INTENTS = frozenset({
    Intent.COVERAGE, Intent.ELIGIBILITY, Intent.CLAIMS,
    Intent.WAITING_PERIOD, Intent.PAYMENT,
})

# "What plans are there?" and "How does cover work?" both classify as
# Intent.COVERAGE - "what plans" is one of that intent's own trigger phrases,
# alongside "cover"/"coverage" - so intent alone cannot tell a menu request
# ("what are my options") apart from a coverage-mechanism question ("what
# does it cover"). Checked against the raw query, not the classified intent,
# specifically for this: an explicit catalogue request always gets the
# general name/positioning/price listing, whatever intent it happened to
# match.
_CATALOG_REQUEST_PHRASES = (
    "what plans", "what products", "what options", "which plans", "which products",
    "list the plans", "list of plans", "show me the plans", "your plans",
)

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

    # ---- Public API -------------------------------------------------------

    def retrieve(
        self,
        query: str,
        product: Product = Product.UNKNOWN,
        intent: Intent = Intent.GENERIC,
    ) -> RetrievalResult:
        if product is Product.UNKNOWN:
            return self._product_overview(query, intent)

        product_data = self.products[product.value]
        query_tokens = _tokenize(query)
        preferred = INTENT_FIELDS.get(intent, ("positioning",))

        facts: list[str] = []
        matches: list[KnowledgeMatch] = []
        matched_tokens: set[str] = set()

        def _hit(field_name: str, text: str) -> int:
            label = FIELD_LABELS.get(field_name, field_name)
            overlap_tokens = query_tokens & _tokenize(f"{label} {text}")
            matched_tokens.update(overlap_tokens)
            return len(overlap_tokens)

        # A payment-method question needs the payment terms, not another
        # marketing overview of a plan the customer is already discussing.
        if intent is not Intent.PAYMENT:
            facts.append(f"**{product_data['name']}**: {product_data['positioning']}")

        for field_name in preferred:
            if field_name in product_data and field_name != "positioning":
                text = product_data[field_name]
                facts.append(f"{FIELD_LABELS.get(field_name, field_name)}: {text}")
                score = _hit(field_name, text)
                matches.append(KnowledgeMatch(product.value, field_name, text, score))

        for field_name, text in product_data.items():
            if field_name in ("id", "name", "keywords", "faq") or field_name in preferred:
                continue
            score = _hit(field_name, str(text))
            if score > 0:
                matches.append(KnowledgeMatch(product.value, field_name, str(text), score))

        matched_tokens |= query_tokens & _tokenize(
            product_data["name"] + " " + " ".join(product_data.get("keywords", []))
        )

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

    def detect_mentioned_products(self, text: str) -> list[Product]:
        """Every product literally named in `text`, in reading order.

        `agent.extraction`'s product classifier is deliberately sticky (one
        product per opportunity, carried forward across turns) and, for a
        message naming two products, an ordering quirk in its phrase list
        picks only one of them. Neither is wrong for its own job, but a
        comparison question needs both sides named, so this is a separate,
        narrow lookup used only for `Intent.COMPARISON`.
        """
        normalized = text.lower()
        hits = [(normalized.find(pid), Product(pid)) for pid in self.products if pid in normalized]
        hits = [hit for hit in hits if hit[0] != -1]
        hits.sort(key=lambda pair: pair[0])
        ordered: list[Product] = []
        for _, product in hits:
            if product not in ordered:
                ordered.append(product)
        return ordered

    def retrieve_comparison(self, product_a: Product, product_b: Product) -> RetrievalResult:
        """Grounded facts for both sides of a comparison, not just one.

        Without this, a "compare A and B" question was silently answered
        about whichever single product `Detection.product` happened to
        settle on, and the other product's facts never appeared at all.
        """
        facts: list[str] = []
        for product in (product_a, product_b):
            data = self.products.get(product.value)
            if data is None:
                continue
            facts.append(f"**{data['name']}**: {data['positioning']}")
            facts.append(f"{FIELD_LABELS['premium']}: {data['premium']}")
        return RetrievalResult(facts=facts, matches=[], confidence=0.9, product=product_a)

    def lookup_field(self, product: Product, field: str) -> Optional[str]:
        """A single named fact about a single product, for a targeted tool call."""
        product_data = self.products.get(product.value)
        if product_data is None:
            return None
        value = product_data.get(field)
        if value is None:
            return None
        label = FIELD_LABELS.get(field, field)
        return f"{product_data['name']} — {label}: {value}"

    def list_products(self) -> list[str]:
        """One approved one-liner per product, for catalogue discovery."""
        return [
            f"**{p['name']}** ({p['id']}): {p['positioning']} {p['premium']}"
            for p in self.kb["products"]
        ]

    def compare(self, product_a: Product, product_b: Product, field: str) -> tuple[str, str]:
        """The same named field for two products, for a side-by-side comparison."""
        a = self.lookup_field(product_a, field) or f"{product_a.value}: not available"
        b = self.lookup_field(product_b, field) or f"{product_b.value}: not available"
        return a, b

    # ---- Internals ----------------------------------------------------------

    @staticmethod
    def _confidence(matched_tokens: int, intent: Intent, preferred_fields: list[str]) -> float:
        if intent is Intent.GENERIC:
            return 0.9
        if preferred_fields:
            if matched_tokens >= 3:
                return 0.95
            if matched_tokens == 2:
                return 0.9
            return 0.85
        if matched_tokens >= 2:
            return 0.7
        return 0.3

    def _product_overview(self, query: str, intent: Intent = Intent.GENERIC) -> RetrievalResult:
        # No lead-in line here: the reply's own opener ("Here's what I can
        # confirm...", "Happy to help...") already introduces the list, so a
        # second, self-describing header rendered as its own bullet only
        # duplicated it. Each entry is a fact in its own right; this line
        # was not.
        #
        # "How does cover work?" and "What plans are there?" both name no
        # product, so both used to retrieve the exact same name/price
        # listing regardless of what was actually asked. When the intent has
        # its own preferred field (coverage, eligibility, claims, ...) and
        # this isn't an explicit catalogue request, show that field per plan
        # instead - a real answer to the question asked.
        is_catalog_request = any(
            phrase in query.lower() for phrase in _CATALOG_REQUEST_PHRASES
        )
        field = (
            INTENT_FIELDS[intent][0]
            if not is_catalog_request and intent in PRODUCT_SURVEY_INTENTS
            else None
        )
        if field:
            facts = [
                f"**{p['name']}** ({p['id']}): {p[field]}" for p in self.kb["products"]
            ]
        else:
            facts = self.list_products()
        return RetrievalResult(facts=facts, matches=[], confidence=0.9, product=Product.UNKNOWN)
