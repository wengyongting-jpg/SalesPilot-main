# -*- coding: utf-8 -*-
"""Aggregate analytics over the opportunity queue. Read-only.

Two properties the previous version did not have, both consequences of the redesign:

**Held conversations are excluded from the sales figures and counted separately.** A
funnel that includes advertising traffic is not a funnel. The previous build had no
way to tell the difference, so spam sat in the queue as a MEDIUM-priority lead.

**Cost is reported.** The token and money totals across every agent run belong next
to the pipeline they paid for.
"""
from __future__ import annotations

from collections import Counter

from ..domain.enums import OpportunityState, Priority, Qualification

# Funnel order, not alphabetical: the sequence is the point of a funnel.
FUNNEL = (
    OpportunityState.COLD_LEAD,
    OpportunityState.POTENTIAL_INTEREST,
    OpportunityState.EVALUATION_HESITATION,
    OpportunityState.HIGH_INTENT,
    OpportunityState.CLOSED_ACTIVE,
    OpportunityState.DORMANT_LOST,
)


class AnalyticsService:
    def __init__(self, repo) -> None:
        self.repo = repo

    def compute(self) -> dict:
        everything = self.repo.list_opportunities()
        sellable = [opp for opp in everything if opp.is_sellable]
        held = [
            opp for opp in everything
            if opp.qualification is Qualification.HELD
        ]
        disqualified = [
            opp for opp in everything
            if opp.qualification is Qualification.DISQUALIFIED
        ]
        cases = self.repo.list_cases()

        by_state = Counter(opp.state.value for opp in sellable)
        by_priority = Counter(
            (opp.priority or Priority.LOW).value for opp in sellable
        )
        by_product = Counter(opp.product.value for opp in sellable)

        signals: Counter[str] = Counter()
        for opp in sellable:
            for signal in opp.signals:
                signals[signal.value] += 1

        scores = [opp.final_score for opp in sellable if opp.final_score is not None]
        converted = by_state.get(OpportunityState.CLOSED_ACTIVE.value, 0)
        lost = by_state.get(OpportunityState.DORMANT_LOST.value, 0)
        resolved = converted + lost

        return {
            # Sales figures count only what is actually a sales opportunity.
            "total_opportunities": len(sellable),
            "by_priority": {
                band.value: by_priority.get(band.value, 0) for band in Priority
            },
            "by_state": {
                state.value: by_state.get(state.value, 0) for state in FUNNEL
            },
            "by_product": dict(sorted(by_product.items())),
            "funnel": [
                {"state": state.value, "count": by_state.get(state.value, 0)}
                for state in FUNNEL
            ],
            "signals": dict(signals.most_common()),
            "average_score": (
                round(sum(scores) / len(scores), 1) if scores else 0.0
            ),
            "escalated_opportunities": sum(
                1 for opp in sellable if opp.human_takeover
            ),
            "human_cases_total": len(cases),
            "human_cases_open": sum(1 for case in cases if case.status.value == "Open"),
            "competitive_risks": sum(1 for opp in sellable if opp.competitive_risk),
            "conversion_rate_of_closed": (
                round(converted / resolved, 3) if resolved else 0.0
            ),
            "converted": converted,
            "lost": lost,
            # Reported separately rather than mixed in, so a reviewer can see how much
            # traffic is being filtered and check that the gate is not overreaching.
            "qualification": {
                "qualified": len(sellable),
                "held": len(held),
                "disqualified": len(disqualified),
            },
            "cost": self._cost(everything),
        }

    def _cost(self, opportunities) -> dict:
        tokens = 0
        amount = 0.0
        runs = 0
        pricing_known = True
        for opp in opportunities:
            totals = self.repo.conversation_totals(opp.id)
            runs += totals["run_count"]
            tokens += totals["total_tokens"]
            amount += totals["cost"]["amount"]
            pricing_known = pricing_known and totals["cost"]["pricing_known"]
        return {
            "agent_runs": runs,
            "total_tokens": tokens,
            "amount": round(amount, 8),
            "currency": "USD",
            "pricing_known": pricing_known,
        }
