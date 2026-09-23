# -*- coding: utf-8 -*-
"""Product classifier — which CareSure product the customer means.

Keyword matching with conversation-history fallback: if the current message
names no product, the classifier carries the most recently mentioned product
forward. Ported from `salespilot/detection/product.py`, retargeted to
`backend.domain.enums.Product`.
"""
from __future__ import annotations

import re
from typing import Optional

from ....domain.enums import Product
from ....domain.message import Message

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


def detect(text: str, context: Optional[list[Message]] = None) -> Product:
    """Classify which CareSure product the customer means, or carry it forward."""
    normalized = text.lower()
    for product, phrases in _PRODUCT_PHRASES:
        if any(phrase in normalized for phrase in phrases):
            return product

    tokens = set(re.findall(r"[a-z]+", normalized))
    for keyword, product in _PRODUCT_KEYWORDS.items():
        if keyword in tokens:
            return product

    if context:
        return _infer_from_context(context)

    return Product.UNKNOWN


def _infer_from_context(context: list[Message]) -> Product:
    """Carry forward the product the *customer* was most recently discussing.

    Scans only customer messages, never the assistant's own prior replies: a
    greeting, an overview or a comparison routinely names every product in
    one message, so scanning it for "the" product mentioned just returns
    whichever keyword happens to be checked first — regardless of what the
    customer actually meant, or whether they'd named a product at all.
    """
    for msg in reversed(context):
        if not msg.is_from_customer:
            continue
        text = msg.text.lower()
        for keyword, product in _PRODUCT_KEYWORDS.items():
            if keyword in text:
                return product
    return Product.UNKNOWN
