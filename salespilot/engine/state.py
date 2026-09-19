# -*- coding: utf-8 -*-
"""Opportunity state machine — six core states.

States:
  1. Cold Lead
  2. Potential Interest
  3. Evaluation & Hesitation
  4. High Intent
  5. Closed / Active Customer
  6. Dormant / Lost

Critical rule: a detected signal does NOT automatically change the state.
Signals update the Opportunity Profile. State changes only when the defined
transition condition is satisfied.

Expansion Opportunity and Churn Risk are flags, not states. The state machine
returns (new_state, reason, flags) where flags may set churn_risk or
expansion on the profile without changing the core state.
"""
from ..detection.signals import SignalDetector
from ..models import Detection, Intent, OpportunityState, Signal

# Intents showing the customer is evaluating a concrete product/price/coverage
_EVALUATION_INTENTS = {
    Intent.PRICE,
    Intent.COVERAGE,
    Intent.COMPARISON,
    Intent.CLAIMS,
    Intent.WAITING_PERIOD,
    Intent.ELIGIBILITY,
    Intent.PAYMENT,
}


class StateTransitionResult:
    """Result of a state transition, including flag updates."""

    def __init__(
        self,
        new_state: OpportunityState,
        reason: str,
        set_churn_risk: bool = False,
        set_expansion: str | None = None,
    ):
        self.new_state = new_state
        self.reason = reason
        self.set_churn_risk = set_churn_risk
        self.set_expansion = set_expansion


class OpportunityStateMachine:
    def __init__(self) -> None:
        self.signal_detector = SignalDetector()

    def transition(
        self,
        current: OpportunityState,
        det: Detection,
        text: str,
        opp_signals: set[Signal] | None = None,
    ) -> StateTransitionResult:
        """Evaluate whether a state transition should fire.

        Uses intent + signals (current turn + accumulated) + text heuristics.
        Signals update the profile separately; here we only check if the
        defined transition condition is satisfied.
        """
        current_signals = set(det.signals)
        accumulated = set(opp_signals or set())
        intent = det.intent
        strong_purchase = (
            Signal.PURCHASE in current_signals
            and intent in (Intent.APPLICATION, Intent.CORPORATE_NEED, Intent.FAMILY_NEED)
        )

        # --- Withdrawal takes highest priority (overrides everything) ---
        if Signal.WITHDRAWAL in current_signals:
            if current == OpportunityState.CLOSED_ACTIVE:
                return StateTransitionResult(
                    OpportunityState.CLOSED_ACTIVE,
                    "Withdrawal from active customer — flag churn risk",
                    set_churn_risk=True,
                )
            return StateTransitionResult(
                OpportunityState.DORMANT_LOST,
                "Explicit purchase withdrawal — customer no longer interested",
            )

        # --- Conversion signal ---
        if Signal.CONVERSION in current_signals and current != OpportunityState.COLD_LEAD:
            return StateTransitionResult(
                OpportunityState.CLOSED_ACTIVE, "Application / payment completed"
            )

        # --- Cancellation / churn (flag, not a new state unless truly lost) ---
        if self.signal_detector.is_cancellation(text):
            if current == OpportunityState.CLOSED_ACTIVE:
                return StateTransitionResult(
                    OpportunityState.CLOSED_ACTIVE,
                    "Churn risk detected — policy may be cancelled",
                    set_churn_risk=True,
                )
            return StateTransitionResult(
                OpportunityState.DORMANT_LOST, "Policy cancelled / lead lost"
            )

        # --- Cold Lead ---
        if current == OpportunityState.COLD_LEAD:
            if intent == Intent.GENERIC:
                return StateTransitionResult(current, "Generic enquiry only")
            return StateTransitionResult(
                OpportunityState.POTENTIAL_INTEREST, "Clear insurance need identified"
            )

        # --- Potential Interest ---
        if current == OpportunityState.POTENTIAL_INTEREST:
            if strong_purchase:
                return StateTransitionResult(
                    OpportunityState.HIGH_INTENT, "Strong purchase preparation"
                )
            if intent in _EVALUATION_INTENTS or Signal.HESITATION in current_signals:
                return StateTransitionResult(
                    OpportunityState.EVALUATION_HESITATION,
                    "Product / price / coverage evaluation"
                )
            return StateTransitionResult(current, "Need nurturing")

        # --- Evaluation & Hesitation ---
        if current == OpportunityState.EVALUATION_HESITATION:
            if strong_purchase:
                return StateTransitionResult(
                    OpportunityState.HIGH_INTENT, "Purchase preparation strengthens"
                )
            if self.signal_detector.is_postponement(text):
                return StateTransitionResult(
                    OpportunityState.DORMANT_LOST, "Explicitly postpones"
                )
            return StateTransitionResult(
                current, "Continued evaluation / address concern"
            )

        # --- High Intent ---
        if current == OpportunityState.HIGH_INTENT:
            # Major new concern (hesitation without purchase in current turn)
            if Signal.HESITATION in current_signals and Signal.PURCHASE not in current_signals:
                return StateTransitionResult(
                    OpportunityState.EVALUATION_HESITATION, "Major new concern"
                )
            return StateTransitionResult(current, "Maintain high intent")

        # --- Closed / Active Customer ---
        if current == OpportunityState.CLOSED_ACTIVE:
            if (
                Signal.EXPANSION_FAMILY in current_signals
                or Signal.EXPANSION_CORPORATE in current_signals
            ):
                flag = "Family" if Signal.EXPANSION_FAMILY in current_signals else "Corporate"
                return StateTransitionResult(
                    OpportunityState.CLOSED_ACTIVE,
                    "New expansion opportunity",
                    set_expansion=flag,
                )
            return StateTransitionResult(current, "Active customer")

        # --- Dormant / Lost ---
        if current == OpportunityState.DORMANT_LOST:
            if intent != Intent.GENERIC:
                return StateTransitionResult(
                    OpportunityState.POTENTIAL_INTEREST, "New insurance need — re-engage"
                )
            return StateTransitionResult(current, "No new need")

        return StateTransitionResult(current, "No matching transition rule")
