# -*- coding: utf-8 -*-
"""Read-only analytics over the repository — `interface-v1.md` §4.2 fields.

JSON-serialisable so the admin API (P6) serves it directly. The opportunity
value score is used for sales prioritisation only and never for an insurance
decision. Ported from `salespilot/analytics/metrics.py`; adds the
qualification breakdown the rebuild introduced (contract item 13).
"""
from __future__ import annotations

from collections import Counter

from ..domain.enums import CaseStatus, OpportunityState, Priority, Qualification
from ..storage.base import Repository

FUNNEL = [
    OpportunityState.COLD_LEAD,
    OpportunityState.POTENTIAL_INTEREST,
    OpportunityState.EVALUATION_HESITATION,
    OpportunityState.HIGH_INTENT,
    OpportunityState.CLOSED_ACTIVE,
    OpportunityState.DORMANT_LOST,
]


class AnalyticsService:
    """Service wrapper for analytics functions."""

    def __init__(self, repo: Repository) -> None:
        self.repo = repo

    def compute_analytics(self) -> dict:
        return compute_analytics(self.repo)

    def health(self) -> dict:
        return health(self.repo)


def compute_analytics(repo: Repository) -> dict:
    opps = repo.list_opportunities()
    # Separate held traffic from the sales funnel
    sellable_opps = [opp for opp in opps if opp.is_sellable]
    cases = repo.list_cases()
    runs = repo.list_runs(limit=1000)  # Get recent runs for cost calculation

    by_state = Counter(opp.state.value for opp in sellable_opps)
    by_priority = Counter((opp.priority or Priority.LOW).value for opp in sellable_opps)
    by_product = Counter(opp.product.value for opp in sellable_opps)
    # Qualification breakdown includes ALL opps (to show held count)
    by_qualification = Counter(opp.qualification.value for opp in opps)
    signal_counts: Counter[str] = Counter(s.value for opp in sellable_opps for s in opp.signals)

    scores = [opp.score.total for opp in sellable_opps if opp.score]
    converted = by_state.get(OpportunityState.CLOSED_ACTIVE.value, 0)
    lost = by_state.get(OpportunityState.DORMANT_LOST.value, 0)
    resolved = converted + lost

    # Calculate total cost from agent runs
    total_cost = 0.0
    for run_dict in runs:
        if run_dict.get("total_cost"):
            total_cost += run_dict["total_cost"]["amount"]

    return {
        "total_opportunities": len(sellable_opps),  # Only sellable opportunities in funnel
        "by_priority": {p.value: by_priority.get(p.value, 0) for p in Priority},
        "by_state": {s.value: by_state.get(s.value, 0) for s in FUNNEL},
        "by_product": dict(sorted(by_product.items())),
        "qualification": {q.value: by_qualification.get(q.value, 0) for q in Qualification},  # Changed key from "by_qualification"
        "funnel": [{"state": s.value, "count": by_state.get(s.value, 0)} for s in FUNNEL],
        "signals": dict(signal_counts.most_common()),
        "average_score": round(sum(scores) / len(scores), 1) if scores else 0.0,
        "escalated_opportunities": sum(1 for opp in sellable_opps if opp.human_takeover),
        "human_cases_total": len(cases),
        "human_cases_open": sum(1 for c in cases if c.status is CaseStatus.OPEN),
        "competitive_risks": sum(1 for opp in sellable_opps if opp.competitive_risk),
        "conversion_rate_of_closed": round(converted / resolved, 3) if resolved else 0.0,
        "converted": converted,
        "lost": lost,
        "cost": round(total_cost, 5),
    }


def health(repo: Repository) -> dict:
    return {
        "status": "ok",
        "conversations": len(repo.list_opportunities()),  # "conversations" is the API term for opportunities
        "opportunities": len(repo.list_opportunities()),  # Keep for backward compatibility
        "open_cases": sum(1 for c in repo.list_cases() if c.status is CaseStatus.OPEN),
        "provider": "template",  # No model configured, using templates
        "degraded": True,  # Template-only mode is degraded
    }
