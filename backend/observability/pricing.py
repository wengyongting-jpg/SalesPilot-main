# -*- coding: utf-8 -*-
"""Token pricing, and therefore cost, computed server-side.

`docs/api/interface-v1.md` §5.3 item 2 is explicit that the price table lives here and
not in a frontend: a console holding pricing would be business logic in the wrong
layer, and it would drift the moment a rate changed.

The distinction this module is careful about is **zero cost versus unknown cost**.
Reporting an unpriced model as $0.00 invites somebody to budget against a number that
means "we have no idea". Every amount therefore travels with `pricing_known`, and an
unknown model returns zero *and says so*.

Rates are USD per million tokens and are indicative. They are configuration, not
truth: check them against the provider before quoting a figure to anyone.
"""
from __future__ import annotations

from dataclasses import dataclass

CURRENCY = "USD"

# model -> (input per 1M tokens, output per 1M tokens)
PRICES: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.00, 8.00),
    # AWS Bedrock standard inference, checked 2026-09-22. The gateway currently
    # reports a global inference-profile id; `_normalise` maps that id here.
    "claude-sonnet-4-5": (3.00, 15.00),
}

_PER_MILLION = 1_000_000


@dataclass(frozen=True)
class Money:
    amount: float
    currency: str = CURRENCY
    # False when the model is absent from the table. The amount is then 0.0, which
    # must not be read as "free".
    pricing_known: bool = True

    def __add__(self, other: "Money") -> "Money":
        if not isinstance(other, Money):
            return NotImplemented
        return Money(
            amount=self.amount + other.amount,
            currency=self.currency,
            # A total is only as trustworthy as its least-known component.
            pricing_known=self.pricing_known and other.pricing_known,
        )

    def to_dict(self) -> dict:
        return {
            "amount": round(self.amount, 8),
            "currency": self.currency,
            "pricing_known": self.pricing_known,
        }

    def describe(self) -> str:
        if not self.pricing_known:
            return "cost unknown"
        return f"${self.amount:.5f}"


def is_known(model: str) -> bool:
    return _normalise(model) in PRICES


def cost_for(model: str, prompt_tokens: int, completion_tokens: int) -> Money:
    rates = PRICES.get(_normalise(model))
    if rates is None:
        return Money(amount=0.0, pricing_known=False)
    input_rate, output_rate = rates
    amount = (
        prompt_tokens * input_rate + completion_tokens * output_rate
    ) / _PER_MILLION
    return Money(amount=amount)


def zero() -> Money:
    return Money(amount=0.0)


def _normalise(model: str) -> str:
    """Strip a gateway prefix and a dated suffix.

    Gateways commonly serve `openai/gpt-4o-mini` or `gpt-4o-mini-2024-07-18`. Failing
    to match those would report every call through a gateway as unpriced, which is
    technically honest and practically useless.
    """
    name = (model or "").strip().lower()
    if "claude-sonnet-4-5" in name:
        return "claude-sonnet-4-5"
    if "/" in name:
        name = name.rsplit("/", 1)[-1]
    if name in PRICES:
        return name
    # Trim a trailing date-like segment, longest match first.
    parts = name.split("-")
    while len(parts) > 1:
        parts.pop()
        candidate = "-".join(parts)
        if candidate in PRICES:
            return candidate
    return name
