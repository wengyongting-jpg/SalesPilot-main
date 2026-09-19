# -*- coding: utf-8 -*-
"""Next Best Action recommendation engine.

Produces a structured result: {action, reason, priority, human_intervention_required}.

Uses State + Signals + Score + Risk Flags to recommend the sales action.
The AI only recommends sales actions — it never makes underwriting, claims
or custom-quotation decisions.
"""
from __future__ import annotations

from ..models import (
    Detection,
    NextBestAction,
    Opportunity,
    OpportunityState,
    Priority,
    Signal,
)


class DecisionEngine:
    def recommend(
        self,
        opp: Opportunity,
        det: Detection,
        escalated: bool = False,
    ) -> NextBestAction:
        """Produce a structured next-best-action recommendation."""
        signals = set(det.signals) | set(opp.signals)
        priority = opp.score.priority if opp.score else Priority.LOW

        # --- Withdrawal: stop active sales ---
        if Signal.WITHDRAWAL in signals:
            return NextBestAction(
                action="Stop active sales follow-up — mark as Dormant/Lost",
                reason="Customer explicitly withdrew purchase intent",
                priority=Priority.LOW,
                human_intervention_required=False,
            )

        # --- Compliance / restricted cases always escalate ---
        if escalated or opp.human_takeover:
            return NextBestAction(
                action="Human take-over: contact the customer and handle the case",
                reason="Restricted case or HITL trigger requires human intervention",
                priority=priority,
                human_intervention_required=True,
            )

        # --- High intent ---
        if opp.state == OpportunityState.HIGH_INTENT:
            if Signal.COMPETITIVE in signals or opp.competitive_risk:
                return NextBestAction(
                    action="Human sales intervention: address competitive risk",
                    reason="High intent with competitive comparison — needs human follow-up",
                    priority=priority,
                    human_intervention_required=True,
                )
            return NextBestAction(
                action="Take over / contact sales",
                reason="High purchase readiness — prioritise immediate sales contact",
                priority=priority,
                human_intervention_required=True,
            )

        # --- Evaluation & Hesitation ---
        if opp.state == OpportunityState.EVALUATION_HESITATION:
            if priority == Priority.HIGH:
                return NextBestAction(
                    action="Sales follow-up",
                    reason="High-value opportunity in evaluation — prioritise follow-up",
                    priority=priority,
                    human_intervention_required=False,
                )
            if Signal.COMPETITIVE in signals:
                return NextBestAction(
                    action="Address competitive concern and nurture",
                    reason="Competitive comparison detected — address value proposition",
                    priority=priority,
                    human_intervention_required=False,
                )
            if Signal.HESITATION in signals:
                return NextBestAction(
                    action="Nurture: identify objection and address concern",
                    reason="Hesitation detected — nurture with grounded information",
                    priority=priority,
                    human_intervention_required=False,
                )
            return NextBestAction(
                action="Address concern with grounded information",
                reason="Continued evaluation — provide factual support",
                priority=priority,
                human_intervention_required=False,
            )

        # --- Potential Interest ---
        if opp.state == OpportunityState.POTENTIAL_INTEREST:
            if (
                Signal.EXPANSION_FAMILY in signals
                or Signal.EXPANSION_CORPORATE in signals
            ):
                return NextBestAction(
                    action="Explore expansion opportunity and recommend the right plan",
                    reason="Expansion signal detected — identify the right product",
                    priority=priority,
                    human_intervention_required=False,
                )
            return NextBestAction(
                action="Continue nurturing and clarify needs",
                reason="Early interest — nurture and guide to the right plan",
                priority=priority,
                human_intervention_required=False,
            )

        # --- Cold Lead ---
        if opp.state == OpportunityState.COLD_LEAD:
            return NextBestAction(
                action="Answer / nurture: provide basic information and clarify needs",
                reason="Cold lead — inform and identify insurance need",
                priority=priority,
                human_intervention_required=False,
            )

        # --- Dormant / Lost ---
        if opp.state == OpportunityState.DORMANT_LOST:
            return NextBestAction(
                action="Schedule a follow-up / re-engage",
                reason="Dormant or lost — attempt re-engagement",
                priority=priority,
                human_intervention_required=False,
            )

        # --- Closed / Active Customer ---
        if opp.state == OpportunityState.CLOSED_ACTIVE:
            if signals & {Signal.EXPANSION_FAMILY, Signal.EXPANSION_CORPORATE}:
                return NextBestAction(
                    action="Create expansion opportunity",
                    reason="Existing customer with expansion signal",
                    priority=priority,
                    human_intervention_required=False,
                )
            if opp.churn_risk:
                return NextBestAction(
                    action="Flag retention risk and trigger retention action",
                    reason="Churn risk detected on active customer",
                    priority=priority,
                    human_intervention_required=True,
                )
            return NextBestAction(
                action="Maintain the relationship",
                reason="Active customer — maintain engagement",
                priority=priority,
                human_intervention_required=False,
            )

        return NextBestAction(
            action="Continue nurturing",
            reason="Default — no specific rule matched",
            priority=priority,
            human_intervention_required=False,
        )
