# -*- coding: utf-8 -*-
"""What human takeover freezes, and what it deliberately does not.

This was `P0-3` in the frozen build, implemented as a boolean threaded through the
middle of a two-hundred-line method, consulted at two distant points and patched
again at the end. Extracting it into one place is most of what makes the rest of the
kernel readable.

The rule, stated once:

**Human takeover means the AI stops making autonomous customer-facing sales
decisions. It does not mean the system stops tracking the customer's lifecycle.**

So while a representative owns the case:

    frozen      the customer-facing state, and the score's floor. A stray "ok" or a
                moment of hesitation must not drag a live opportunity back toward a
                cold lead, or collapse its value, while a human is working it. The
                profile is the representative's context; it has to stay stable.

    not frozen  the customer's explicit withdrawal. A reported payment is not a
                trusted conversion signal; only a staff action or a trusted order
                system may confirm the sale.

Ambiguous, generic and hesitant messages stay frozen, which is the asymmetry that
matters: an explicit statement of outcome is trustworthy evidence, a vague one is not.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..domain.detection import Detection
from ..domain.enums import Signal
from ..domain.opportunity import Opportunity

# The two signals that represent the customer deciding something themselves.
_LIFECYCLE_SIGNALS = (Signal.WITHDRAWAL,)


@dataclass
class TakeoverDecision:
    active: bool
    freeze_state: bool
    preserve_score_floor: bool
    lifecycle_exception: bool
    reason: str


def evaluate(opp: Opportunity, det: Detection) -> TakeoverDecision:
    """Decide what this turn is allowed to change.

    Pure. The caller applies the decision; nothing here mutates the opportunity.
    """
    active = opp.human_takeover
    if not active:
        return TakeoverDecision(
            active=False,
            freeze_state=False,
            preserve_score_floor=False,
            lifecycle_exception=False,
            reason="No human takeover — the pipeline proceeds normally",
        )

    signals = set(det.signals)
    lifecycle = [signal for signal in _LIFECYCLE_SIGNALS if signal in signals]
    if lifecycle:
        names = " and ".join(signal.value for signal in lifecycle)
        return TakeoverDecision(
            active=True,
            freeze_state=False,
            preserve_score_floor=False,
            lifecycle_exception=True,
            reason=(
                f"Takeover is active, but {names} is the customer's own decision, "
                "so the opportunity still moves. Takeover remains in force."
            ),
        )

    return TakeoverDecision(
        active=True,
        freeze_state=True,
        preserve_score_floor=True,
        lifecycle_exception=False,
        reason=(
            "Takeover is active and this message carries no explicit lifecycle "
            "decision, so the customer-facing state and the score floor are held "
            "steady for the representative"
        ),
    )
