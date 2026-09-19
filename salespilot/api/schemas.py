# -*- coding: utf-8 -*-
"""Pydantic request/response schemas for the FastAPI service layer.

Imported lazily by api/app.py so the core agent stays usable without
fastapi/pydantic installed.
"""
from __future__ import annotations

from typing import Optional

try:
    from pydantic import BaseModel, Field
except ImportError:  # allow the module to import without pydantic
    BaseModel = object  # type: ignore[assignment, misc]

    def Field(*args, **kwargs):  # type: ignore[no-redef]
        return args[0] if args else None


class IncomingMessage(BaseModel):
    customer_id: str = ""
    customer_name: str
    text: str = Field(..., min_length=1)


def serialize_next_best_action(nba) -> dict:
    return {
        "action": nba.action,
        "reason": nba.reason,
        "priority": nba.priority.value,
        "human_intervention_required": nba.human_intervention_required,
    }


def serialize_opportunity(opp) -> dict:
    return {
        "opportunity_id": opp.id,
        "customer_name": opp.customer_name,
        "state": opp.state.value,
        "product": opp.product.value,
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
        "messages": [
            {"ts": m.ts.isoformat() if m.ts else None, "role": m.role, "text": m.text}
            for m in opp.messages
        ],
    }


def serialize_case(case) -> dict:
    return {
        "id": case.id,
        "opportunity_id": case.opportunity_id,
        "customer_name": case.customer_name,
        "state": case.state.value,
        "product": case.product.value,
        "reason": case.reason,
        "summary": case.summary,
        "recommended_action": case.recommended_action,
        "status": case.status.value,
        "created_at": case.created_at.isoformat(),
    }


def serialize_agent_result(result) -> dict:
    return {
        "reply": result.reply,
        "opportunity": serialize_opportunity(result.opportunity),
        "detection": {
            "intent": result.detection.intent.value,
            "product": result.detection.product.value,
            "signals": [s.value for s in result.detection.signals],
            "concerns": result.detection.concerns,
            "restricted": result.detection.restricted,
        },
        "retrieval": {
            "facts": result.retrieval.facts,
            "confidence": result.retrieval.confidence,
            "product": result.retrieval.product.value,
        },
        "score": {
            "purchase_intent": result.score.purchase_intent,
            "purchase_readiness": result.score.purchase_readiness,
            "product_potential": result.score.product_potential,
            "expansion": result.score.expansion,
            "engagement": result.score.engagement,
            "total": result.score.total,
            "priority": result.score.priority.value,
        },
        "state_change": result.state_change,
        "next_best_action": serialize_next_best_action(result.next_best_action),
        "case": serialize_case(result.case) if result.case else None,
        "extraction_source": getattr(result, "extraction_source", "rule"),
    }
