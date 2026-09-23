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


def compute_analytics(repo: Repository) -> dict:
    opps = repo.list_opportunities()
    cases = repo.list_cases()

    by_state = Counter(opp.state.value for opp in opps)
    by_priority = Counter((opp.priority or Priority.LOW).value for opp in opps)
    by_product = Counter(opp.product.value for opp in opps)
    by_qualification = Counter(opp.qualification.value for opp in opps)
    signal_counts: Counter[str] = Counter(s.value for opp in opps for s in opp.signals)

    scores = [opp.score.total for opp in opps if opp.score]
    converted = by_state.get(OpportunityState.CLOSED_ACTIVE.value, 0)
    lost = by_state.get(OpportunityState.DORMANT_LOST.value, 0)
    resolved = converted + lost

    return {
        "total_opportunities": len(opps),
        "by_priority": {p.value: by_priority.get(p.value, 0) for p in Priority},
        "by_state": {s.value: by_state.get(s.value, 0) for s in FUNNEL},
        "by_product": dict(sorted(by_product.items())),
        "by_qualification": {q.value: by_qualification.get(q.value, 0) for q in Qualification},
        "funnel": [{"state": s.value, "count": by_state.get(s.value, 0)} for s in FUNNEL],
        "signals": dict(signal_counts.most_common()),
        "average_score": round(sum(scores) / len(scores), 1) if scores else 0.0,
        "escalated_opportunities": sum(1 for opp in opps if opp.human_takeover),
        "human_cases_total": len(cases),
        "human_cases_open": sum(1 for c in cases if c.status is CaseStatus.OPEN),
        "competitive_risks": sum(1 for opp in opps if opp.competitive_risk),
        "conversion_rate_of_closed": round(converted / resolved, 3) if resolved else 0.0,
        "converted": converted,
        "lost": lost,
    }


def health(repo: Repository) -> dict:
    return {
        "status": "ok",
        "opportunities": len(repo.list_opportunities()),
        "open_cases": sum(1 for c in repo.list_cases() if c.status is CaseStatus.OPEN),
    }
