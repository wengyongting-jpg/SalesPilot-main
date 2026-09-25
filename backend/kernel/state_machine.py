# -*- coding: utf-8 -*-
"""The opportunity state machine: six states, in funnel order.

    Cold Lead -> Potential Interest -> Evaluation & Hesitation -> High Intent
              -> Closed / Active Customer   or   Dormant / Lost

**A detected signal does not by itself change the state.** Signals update the
profile; the state moves only when a defined transition condition is met. Conflating
the two is how "I want Plus" used to look like purchase preparation.

Expansion and churn are flags, not states, because a customer occupies exactly one
state while carrying any combination of flags. The transition therefore returns flag
updates alongside the new state rather than encoding them as destinations.

Note on layering: the frozen build's state machine imported the signal detector so
it could run two text heuristics — cancellation and postponement — itself. That
inverted the dependency, putting extraction logic inside the deterministic core.
Both are observations, so they now arrive on `Detection` and this module only reads
them. `backend/tests/test_architecture.py` fails the build if that inversion returns.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..domain.detection import Detection
from ..domain.enums import Intent, OpportunityState, Signal

# Intents that indicate the customer is weighing a concrete plan, price or benefit
# rather than making a general enquiry.
_EVALUATION_INTENTS = {
    Intent.PRICE,
    Intent.COVERAGE,
    Intent.COMPARISON,
    Intent.CLAIMS,
    Intent.WAITING_PERIOD,
    Intent.ELIGIBILITY,
    Intent.PAYMENT,
}

# Purchase preparation only counts as "strong" when it is attached to an intent that
# implies acting, not merely wanting.
_PREPARATION_INTENTS = {
    Intent.APPLICATION,
    Intent.CORPORATE_NEED,
    Intent.FAMILY_NEED,
}


@dataclass
class StateTransition:
    new_state: OpportunityState
    reason: str
    set_churn_risk: bool = False
    set_expansion: Optional[str] = None

    @property
    def moved(self) -> bool:
        return self.reason is not None


def transition(
    current: OpportunityState,
    det: Detection,
    *,
    accumulated_signals: Optional[set[Signal]] = None,
) -> StateTransition:
    """Evaluate whether a transition fires, and which flags it sets.

    `accumulated_signals` lets a rule consider the conversation's history as well as
    this turn. It is accepted rather than read off an opportunity so this function
    stays a pure function of its inputs.
    """
    signals = set(det.signals)
    _ = set(accumulated_signals or set())
    intent = det.intent
    strong_preparation = Signal.PURCHASE in signals and intent in _PREPARATION_INTENTS

    # --- Withdrawal outranks everything else -----------------------------
    if Signal.WITHDRAWAL in signals:
        if current is OpportunityState.CLOSED_ACTIVE:
            return StateTransition(
                OpportunityState.CLOSED_ACTIVE,
                "Withdrawal by an active customer — flag churn risk",
                set_churn_risk=True,
            )
        return StateTransition(
            OpportunityState.DORMANT_LOST,
            "Explicit purchase withdrawal — no longer interested",
        )

    # --- Conversion -------------------------------------------------------
    # Conversion is deliberately not inferred from a customer message. A customer
    # can report that they paid, but only a staff action or trusted order-system
    # event may move an opportunity into CLOSED_ACTIVE. Detection has no authority
    # to certify either event, so Signal.CONVERSION is retained as an observation
    # for context/scoring only.

    # --- Cancellation: churn for a customer, a lost lead otherwise --------
    if det.cancellation:
        if current is OpportunityState.CLOSED_ACTIVE:
            return StateTransition(
                OpportunityState.CLOSED_ACTIVE,
                "Churn risk — the policy may be cancelled",
                set_churn_risk=True,
            )
        return StateTransition(
            OpportunityState.DORMANT_LOST, "Cancelled — lead lost"
        )

    # A current explicit deferral overrides historical readiness in every
    # non-customer lifecycle state, including High Intent.
    if det.postponement and current is not OpportunityState.CLOSED_ACTIVE:
        return StateTransition(
            OpportunityState.DORMANT_LOST, "Customer deferred the purchase"
        )

    if current is OpportunityState.COLD_LEAD:
        if intent is Intent.GENERIC:
            return StateTransition(current, "Generic enquiry only")
        return StateTransition(
            OpportunityState.POTENTIAL_INTEREST, "Clear insurance need identified"
        )

    if current is OpportunityState.POTENTIAL_INTEREST:
        if strong_preparation:
            return StateTransition(
                OpportunityState.HIGH_INTENT, "Strong purchase preparation"
            )
        if intent in _EVALUATION_INTENTS or Signal.HESITATION in signals:
            return StateTransition(
                OpportunityState.EVALUATION_HESITATION,
                "Evaluating a plan, price or benefit",
            )
        return StateTransition(current, "Still needs nurturing")

    if current is OpportunityState.EVALUATION_HESITATION:
        if strong_preparation:
            return StateTransition(
                OpportunityState.HIGH_INTENT, "Purchase preparation strengthens"
            )
        if det.postponement:
            return StateTransition(
                OpportunityState.DORMANT_LOST, "Explicitly postponed"
            )
        return StateTransition(current, "Continued evaluation — address the concern")

    if current is OpportunityState.HIGH_INTENT:
        # A fresh concern without any purchase evidence in the same turn is a real
        # step backwards; alongside purchase evidence it is just a question.
        if Signal.HESITATION in signals and Signal.PURCHASE not in signals:
            return StateTransition(
                OpportunityState.EVALUATION_HESITATION, "A major new concern"
            )
        return StateTransition(current, "Maintains high intent")

    if current is OpportunityState.CLOSED_ACTIVE:
        if Signal.EXPANSION_CORPORATE in signals:
            return StateTransition(
                current, "New expansion opportunity", set_expansion="Corporate"
            )
        if Signal.EXPANSION_FAMILY in signals:
            return StateTransition(
                current, "New expansion opportunity", set_expansion="Family"
            )
        return StateTransition(current, "Active customer")

    if current is OpportunityState.DORMANT_LOST:
        if intent is not Intent.GENERIC:
            return StateTransition(
                OpportunityState.POTENTIAL_INTEREST,
                "A new insurance need — re-engage",
            )
        return StateTransition(current, "No new need")

    return StateTransition(current, "No matching transition rule")
