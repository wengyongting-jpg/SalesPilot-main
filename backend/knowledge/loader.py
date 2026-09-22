# -*- coding: utf-8 -*-
"""Loading the product knowledge base.

Every factual claim the assistant makes about a product must come from here. The
assistant has no other source of product information, which is the whole point: an
answer that cannot be grounded is escalated rather than improvised.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

from .. import config
from ..domain.enums import KnowledgeField, Product

# Human-readable labels, used when a fact is presented to a customer. The enum value
# is the machine name; this is what a person should read.
FIELD_LABELS: dict[KnowledgeField, str] = {
    KnowledgeField.POSITIONING: "Overview",
    KnowledgeField.TARGET_CUSTOMER: "Target customer",
    KnowledgeField.ELIGIBILITY: "Eligibility",
    KnowledgeField.COVERAGE: "Coverage",
    KnowledgeField.PREMIUM: "Indicative premium",
    KnowledgeField.DEDUCTIBLE: "Deductible and co-payment",
    KnowledgeField.LIMITS: "Coverage limit",
    KnowledgeField.WAITING_PERIOD: "Waiting period",
    KnowledgeField.EXCLUSIONS: "Exclusions",
    KnowledgeField.CLAIMS: "Claims process",
    KnowledgeField.PAYMENT: "Payment",
    KnowledgeField.RENEWAL: "Renewal",
}


@dataclass(frozen=True)
class KnowledgeBase:
    company: str
    disclaimer: str
    products: dict[str, dict]

    def product(self, product: Product) -> Optional[dict]:
        return self.products.get(product.value)

    def field(self, product: Product, field: KnowledgeField) -> Optional[str]:
        """One approved fact, or None.

        Returns None rather than a best guess: a caller that cannot ground its answer
        must escalate, and a plausible substitute would prevent it from noticing.
        """
        data = self.product(product)
        if data is None:
            return None
        value = data.get(field.value)
        return str(value) if value is not None else None

    def name(self, product: Product) -> Optional[str]:
        data = self.product(product)
        return data["name"] if data else None

    def keywords(self, product: Product) -> list[str]:
        data = self.product(product)
        return list(data.get("keywords", [])) if data else []

    def faq(self, product: Product) -> list[dict]:
        data = self.product(product)
        return list(data.get("faq", [])) if data else []

    def overview(self) -> list[str]:
        """One line per plan, for a customer who has not named one yet."""
        return [
            f"- {data['name']}: {data['positioning']} {data['premium']}"
            for data in self.products.values()
        ]

    def catalogue_order(self) -> list[Product]:
        """The plans in the order the knowledge base lists them."""
        return [Product(product_id) for product_id in self.products]


@lru_cache(maxsize=4)
def load(path: Optional[str] = None) -> KnowledgeBase:
    """Load and cache the knowledge base.

    Cached because it is immutable and read on every message; keyed by path so a
    test can load a fixture without disturbing the default.
    """
    target = Path(path) if path else config.KB_PATH
    with open(target, "r", encoding="utf-8") as handle:
        raw = json.load(handle)
    return KnowledgeBase(
        company=raw["company"],
        disclaimer=raw["demo_disclaimer"],
        products={product["id"]: product for product in raw["products"]},
    )
