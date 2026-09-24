# -*- coding: utf-8 -*-
"""Product classification by keyword, carried forward through context.

Product is sticky on purpose: once a conversation is about Plus, "how much is it?"
is still about Plus. Re-deciding from each message in isolation is what makes an
assistant ask which plan you meant three times in a row.
"""
from __future__ import annotations

from ....domain.enums import Product

# Ordered so that the more specific segment wins: a message mentioning both
# employees and a family is a corporate enquiry.
_KEYWORDS: list[tuple[Product, tuple[str, ...]]] = [
    (Product.CORPORATE, (
        "corporate", "employee", "employees", "staff", "company", "companies",
        "sme", "business", "workforce", "employer", "group insurance", "team",
    )),
    (Product.PLUS, (
        # Deliberately no bare "private hospital": it is a coverage-tier
        # descriptor a customer can use while stating a family or corporate
        # need ("private hospital cover for me and my two children" is a
        # family need, not a Plus-specific request), so it must not outrank
        # an explicit family/corporate member reference checked below.
        "plus", "private ward", "premium plan", "top tier",
        "comprehensive", "best coverage", "a ward", "specialist of my choice",
    )),
    (Product.FAMILY, (
        "family", "spouse", "wife", "husband", "child", "children", "kids",
        "daughter", "son", "dependant", "dependent", "newborn", "household",
    )),
    (Product.ESSENTIAL, (
        "essential", "basic", "entry", "affordable", "cheapest", "cheap",
        "b1", "young professional", "first insurance", "starter", "budget",
    )),
]

_EMPLOYEE_COUNT_HINTS = ("employees", "headcount", "staff of")


def detect(text: str, context: list | None = None) -> Product:
    lowered = f" {text.lower().strip()} "

    for product, keywords in _KEYWORDS:
        if any(keyword in lowered for keyword in keywords):
            return product

    # "We have 120 people" — a number next to a workforce word is corporate.
    if any(hint in lowered for hint in _EMPLOYEE_COUNT_HINTS):
        return Product.CORPORATE

    # Nothing in this message: inherit from what the CUSTOMER said earlier.
    #
    # Only their messages. The assistant's own replies are not evidence of what the
    # customer wants, and its overview reply names all four plans — so scanning them
    # inherits whichever plan the keyword tables happen to check first. That was a
    # real defect: a customer who asked for the cheapest basic plan and then said
    # "that seems a little expensive for me" inherited *Corporate* from the
    # assistant's own text, quadrupling his product potential and pushing a hesitant
    # budget shopper to HIGH priority.
    if context:
        for message in reversed(context):
            if not _is_from_customer(message):
                continue
            inherited = _from_text(message.text)
            if inherited is not Product.UNKNOWN:
                return inherited

    return Product.UNKNOWN


def _is_from_customer(message) -> bool:
    """Whether a context entry came from the customer.

    Tolerant of a plain object with a `role` string as well as a domain `Message`, so
    a caller assembling context by hand cannot silently opt out of the check.
    """
    flag = getattr(message, "is_from_customer", None)
    if isinstance(flag, bool):
        return flag
    role = getattr(message, "role", None)
    value = getattr(role, "value", role)
    return value == "customer"


def _from_text(text: str) -> Product:
    lowered = f" {text.lower().strip()} "
    for product, keywords in _KEYWORDS:
        if any(keyword in lowered for keyword in keywords):
            return product
    return Product.UNKNOWN
