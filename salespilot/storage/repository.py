# -*- coding: utf-8 -*-
"""Opportunity / human-case repository (in-memory; replaceable with a database).

Also offers simple JSON export (a reserved hook for FR-13 audit retention).
The demo flow does not write files by itself to avoid side effects.
"""
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from .. import config
from ..models import HumanCase, Opportunity
from .base import BaseRepository


class Repository(BaseRepository):
    """Default in-memory repository (process lifetime; swap for SqliteRepository)."""

    def __init__(self) -> None:
        self._opportunities: dict[str, Opportunity] = {}
        self._cases: dict[str, HumanCase] = {}

    # ---- Opportunities ---------------------------------------------------

    def upsert_opportunity(self, opp: Opportunity) -> None:
        opp.updated_at = datetime.now()
        self._opportunities[opp.id] = opp

    def get_opportunity(self, opp_id: str) -> Optional[Opportunity]:
        return self._opportunities.get(opp_id)

    def list_opportunities(self) -> list[Opportunity]:
        return list(self._opportunities.values())

    def delete_opportunity(self, opp_id: str) -> None:
        self._opportunities.pop(opp_id, None)

    # ---- HITL cases ------------------------------------------------------

    def add_case(self, case: HumanCase) -> None:
        self._cases[case.id] = case

    def update_case(self, case: HumanCase) -> None:
        self._cases[case.id] = case

    def list_cases(self) -> list[HumanCase]:
        return list(self._cases.values())

    # ---- Optional JSON export -------------------------------------------

    def save(self, path: Optional[Path] = None) -> Path:
        config.RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        target = path or (config.RUNTIME_DIR / "salespilot_state.json")

        def _default(obj):
            if isinstance(obj, datetime):
                return obj.isoformat()
            if hasattr(obj, "value"):  # Enum
                return obj.value
            return asdict(obj)

        payload = {
            "opportunities": [
                _slim_opportunity(o) for o in self._opportunities.values()
            ],
            "cases": [asdict(c) for c in self._cases.values()],
        }
        with open(target, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2, default=_default)
        return target


def _slim_opportunity(opp: Opportunity) -> dict:
    """Fields kept for sales review (spec: What Should Be Saved for Sales Review)."""
    return {
        "opportunity_id": opp.id,
        "customer_name": opp.customer_name,
        "product": opp.product.value,
        "state": opp.state.value,
        "signals": [s.value for s in opp.signals],
        "signal_history": [s.value for s in opp.signal_history],
        "main_concern": opp.main_concern,
        "competitive_risk": opp.competitive_risk,
        "churn_risk": opp.churn_risk,
        "compliance_risk": opp.compliance_risk,
        "expansion": opp.expansion,
        "priority": opp.score.priority.value if opp.score else None,
        "final_score": opp.score.total if opp.score else None,
        "score_history": [
            {"ts": e.timestamp.isoformat(), "score": e.score, "state": e.state, "trigger": e.trigger}
            for e in opp.score_history
        ],
        "state_history": [
            {"ts": e.timestamp.isoformat(), "from": e.from_state, "to": e.to_state, "reason": e.reason}
            for e in opp.state_history
        ],
        "human_takeover": opp.human_takeover,
        "human_intervention_required": opp.human_intervention_required,
        "turns": opp.turns,
    }
