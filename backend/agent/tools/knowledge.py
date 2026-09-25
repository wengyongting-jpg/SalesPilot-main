# -*- coding: utf-8 -*-
"""Read-only knowledge tools.

Typed by `domain.enums.Product` and `domain.enums.KnowledgeField`, so the model
cannot ask for a plan or a field that does not exist and then be handed something
improvised. When a lookup has no answer these say so plainly: an assistant that
cannot ground a claim must be able to notice, and a plausible substitute would
prevent exactly that.
"""
from __future__ import annotations

from ...domain.enums import KnowledgeField, Product
from ...knowledge.loader import FIELD_LABELS
from . import ToolContext

_UNAVAILABLE = (
    "That information is not available in the approved knowledge base. Do not "
    "guess — say you will have a colleague confirm it."
)


def lookup_product_fact(
    context: ToolContext, product: Product, field: KnowledgeField
) -> str:
    """One approved fact about one plan."""
    text = context.kb.field(product, field)
    if text is None:
        result = _UNAVAILABLE
    else:
        result = f"{context.kb.name(product)} — {FIELD_LABELS[field]}: {text}"
    return context.record(
        "lookup_product_fact",
        {"product": product.value, "field": field.value},
        result,
    )


def compare_products(
    context: ToolContext, field: KnowledgeField, products: list[Product]
) -> str:
    """The same field across two or more plans, side by side.

    This is the tool that makes multi-hop reasoning possible: "compare the waiting
    period of Plus and Family" needs two lookups and a contrast, which a single
    intent-keyed retrieval cannot express. It is also why the loop exists at all —
    without it the model would have no reason ever to call a tool twice.
    """
    lines = [f"{FIELD_LABELS[field]}:"]
    for product in products:
        text = context.kb.field(product, field)
        name = context.kb.name(product) or product.value
        lines.append(f"- {name}: {text if text else 'not available'}")
    result = "\n".join(lines)
    return context.record(
        "compare_products",
        {"field": field.value, "products": [p.value for p in products]},
        result,
    )


def list_products(context: ToolContext) -> str:
    """Every plan with its one-line positioning.

    Exposed as a tool rather than baked into the system prompt so the catalogue has
    one source. A prompt listing plans is another copy that can fall out of step with
    the knowledge base.
    """
    result = "\n".join(
        [f"{context.kb.company} plans:"] + context.kb.overview()
    )
    return context.record("list_products", {}, result)
