# -*- coding: utf-8 -*-
"""Read-only knowledge tools: what the model may look up.

Idempotent, no side effects. `compare_products` exists as its own tool
(rather than two `lookup_product_fact` calls) so a single call can ground a
comparison; the model may still call `lookup_product_fact` twice in one run
for a multi-hop lookup, which is the acceptance scenario in
`docs/backend-plan.md` §9 ("compare the waiting period of Plus and Family").
"""
from __future__ import annotations

from ...domain.enums import Product
from ...knowledge.retriever import KnowledgeRetriever

_retriever = KnowledgeRetriever()


def lookup_product_fact(product: Product, field: str) -> str:
    """Look up one named fact (e.g. "premium", "coverage", "waiting_period") for a product."""
    fact = _retriever.lookup_field(product, field)
    if fact is None:
        return f"No approved fact found for {product.value}/{field}."
    return fact


def compare_products(product_a: Product, product_b: Product, field: str) -> str:
    """Compare the same named fact across two products."""
    a, b = _retriever.compare(product_a, product_b, field)
    return f"{a}\n{b}"


def list_products() -> str:
    """List every CareSure product with a one-line overview, for catalogue discovery."""
    return "\n".join(_retriever.list_products())
