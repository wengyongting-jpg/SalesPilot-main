# -*- coding: utf-8 -*-
"""Basic sales analytics computed from the repository (FR-15).

Everything here is read-only and JSON-serialisable so the API layer can serve
it directly to a future web dashboard. The Opportunity Value Score is used for
sales prioritisation only and never for insurance decisions.
"""
from __future__ import annotations

from collections import Counter

from ..models import OpportunityState, Priority, Signal
from ..storage import BaseRepository

# Ordered funnel states for the pipeline view
_FUNNEL = [
    OpportunityState.COLD_LEAD,
    OpportunityState.POTENTIAL_INTEREST,
    OpportunityState.EVALUATION_HESITATION,
    OpportunityState.HIGH_INTENT,
    OpportunityState.CLOSED_ACTIVE,
    OpportunityState.DORMANT_LOST,
]


def compute_analytics(repo: BaseRepository) -> dict:
    opps = repo.list_opportunities()
    cases = repo.list_cases()
    total = len(opps)

    by_state = Counter(opp.state.value for opp in opps)
    by_priority = Counter(
        opp.score.priority.value if opp.score else Priority.LOW.value
        for opp in opps
    )
    by_product = Counter(
        opp.product.value for opp in opps
    )

    signal_counts: Counter[str] = Counter()
    for opp in opps:
        for signal in opp.signals:
            signal_counts[signal.value] += 1

    scores = [opp.score.total for opp in opps if opp.score]
    avg_score = round(sum(scores) / len(scores), 1) if scores else 0.0

    converted = by_state.get(OpportunityState.CLOSED_ACTIVE.value, 0)
    lost = by_state.get(OpportunityState.DORMANT_LOST.value, 0)
    resolved = converted + lost
    conversion_rate = round(converted / resolved, 3) if resolved else 0.0

    return {
        "total_opportunities": total,
        "by_priority": {
            Priority.HIGH.value: by_priority.get(Priority.HIGH.value, 0),
            Priority.MEDIUM.value: by_priority.get(Priority.MEDIUM.value, 0),
            Priority.LOW.value: by_priority.get(Priority.LOW.value, 0),
        },
        "by_state": {state.value: by_state.get(state.value, 0) for state in _FUNNEL},
        "by_product": dict(sorted(by_product.items())),
        "funnel": [
            {"state": state.value, "count": by_state.get(state.value, 0)}
            for state in _FUNNEL
        ],
        "signals": dict(signal_counts.most_common()),
        "average_score": avg_score,
        "escalated_opportunities": sum(1 for opp in opps if opp.human_takeover),
        "human_cases_total": len(cases),
        "human_cases_open": sum(1 for c in cases if c.status.value == "Open"),
        "competitive_risks": sum(
            1 for opp in opps if opp.competitive_risk
        ),
        "conversion_rate_of_closed": conversion_rate,
        "converted": converted,
        "lost": lost,
    }
