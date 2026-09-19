# -*- coding: utf-8 -*-
"""Product classifier — which CareSure product the customer means.

Uses keyword matching, with conversation-history fallback:
if the current message does not mention any product keyword, the classifier
looks at recent messages to carry the product forward.
"""
from __future__ import annotations

import re

from ..models import Message, Product

# Order is priority: strong company/family signals come before generic words
_PRODUCT_PHRASES: list[tuple[Product, tuple[str, ...]]] = [
    (Product.CORPORATE, (
        "corporate", "employee", "employees", "staff", "sme", "company",
        "business", "workforce", "employer", "group",
    )),
    (Product.FAMILY, (
        "family plan", "family package", "family cover", "family coverage",
        "family of", "for my family", "family needs", "family insurance",
    )),
    (Product.PLUS, (
        "caresure plus", "plus plan", "the plus plan", "private hospital",
        "private healthcare", "enhanced plan", "premium plan", "higher coverage",
    )),
    (Product.ESSENTIAL, (
        "essential", "basic plan", "cheapest", "entry plan", "affordable plan",
        "b1", "first plan",
    )),
]

_PRODUCT_KEYWORDS = {
    "plus": Product.PLUS,
    "essential": Product.ESSENTIAL,
    "family": Product.FAMILY,
    "corporate": Product.CORPORATE,
}


class ProductClassifier:
    def detect(
        self,
        text: str,
        context: list[Message] | None = None,
    ) -> Product:
        """Classify which CareSure product the customer is asking about.

        Falls back to conversation history when the current message has no
        product keyword (e.g. "how much is it?" after discussing Plus).
        """
        normalized = text.lower()
        for product, phrases in _PRODUCT_PHRASES:
            if any(phrase in normalized for phrase in phrases):
                return product

        # Whole-word product-name match (e.g. "How much is Plus?"). Uses word
        # boundaries so "surplus" / "families" do not false-match.
        tokens = set(re.findall(r"[a-z]+", normalized))
        for keyword, product in _PRODUCT_KEYWORDS.items():
            if keyword in tokens:
                return product

        # No direct match — try to carry product from conversation history
        if context:
            return self._infer_from_context(context)

        return Product.UNKNOWN

    @staticmethod
    def _infer_from_context(context: list[Message]) -> Product:
        """Carry forward the most recently mentioned product."""
        for msg in reversed(context):
            text = msg.text.lower()
            for keyword, product in _PRODUCT_KEYWORDS.items():
                if keyword in text:
                    return product
        return Product.UNKNOWN
