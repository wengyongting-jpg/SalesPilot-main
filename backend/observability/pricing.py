# -*- coding: utf-8 -*-
"""Token price table → cost, computed server-side.

A frontend holding prices would be business logic in the wrong layer
(`interface-v1.md` §5.3 requirement 2), so the table lives here. It is
deliberately a small static table rather than a live price feed: a run's
recorded cost must be reproducible from the stored record.

Unknown model or no tokens → `None`, never `0`: an absent cost means "not
priced", a zero would claim the call was free (`backend-contract.md` item 8,
acceptance 5). Swap point: if a maintained price source is ever adopted,
`cost_for` is the only function that changes.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from .run import Cost

# (input USD per million tokens, output USD per million tokens)
PRICES_USD_PER_MILLION: dict[str, tuple[Decimal, Decimal]] = {
    "gpt-4o-mini": (Decimal("0.15"), Decimal("0.60")),
    "gpt-4o": (Decimal("2.50"), Decimal("10.00")),
    "gpt-4.1-mini": (Decimal("0.40"), Decimal("1.60")),
    "gpt-4.1": (Decimal("2.00"), Decimal("8.00")),
    # Anthropic's published standard list price for Sonnet 4.5 global
    # cross-region inference (USD per million input/output tokens; <=200K
    # context). This project caps prompts far below that context tier.
    "global.anthropic.claude-sonnet-4-5": (Decimal("3.00"), Decimal("15.00")),
    "anthropic.claude-sonnet-4-5": (Decimal("3.00"), Decimal("15.00")),
    "claude-sonnet-4-5": (Decimal("3.00"), Decimal("15.00")),
}

_MILLION = Decimal(1_000_000)


def is_known(model: str) -> bool:
    """Whether `model` (after normalising a dated snapshot) has a price entry.

    `agent.model_factory` checks this before deciding whether a call can be
    wrapped for enforced cost accounting — an unpriced model must not be
    silently treated as free, so callers that need the cost budget enforced
    (`backend.evals`) stop rather than proceed on faith.
    """
    return _normalise(model) in PRICES_USD_PER_MILLION


def cost_for(model: str, prompt_tokens: int, completion_tokens: int) -> Optional[Cost]:
    if prompt_tokens <= 0 and completion_tokens <= 0:
        return None
    prices = PRICES_USD_PER_MILLION.get(_normalise(model))
    if prices is None:
        return None
    input_price, output_price = prices
    amount = (
        Decimal(prompt_tokens) * input_price + Decimal(completion_tokens) * output_price
    ) / _MILLION
    return Cost(amount=amount)


def _normalise(model: str) -> str:
    # Providers often report a dated snapshot ("gpt-4o-mini-2024-07-18");
    # price it as its base model.
    name = model.strip().lower()
    for known in sorted(PRICES_USD_PER_MILLION, key=len, reverse=True):
        if name == known or name.startswith(known + "-"):
            return known
    return name
