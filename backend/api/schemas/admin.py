# -*- coding: utf-8 -*-
"""Admin-tier serialisation: the full opportunity intelligence.

The frozen `interface-v1.md` §4.2 opportunity object, kept key for key so an
adapter written against it still works, plus what the rebuild added:
`customer_message_count` beside the deprecated `turns` alias (§1.1), the two
scoring axes and the qualification gate (contract item 13), and messages that
carry `id`, `author`, `generation` and `rep_name`.
"""
from __future__ import annotations

from typing import Optional

from ...domain.case import HumanCase
from ...domain.message import Message
from ...domain.opportunity import Opportunity, ScoreCard
from .shared import case_to_wire, message_to_wire

DEFAULT_HISTORY_LIMIT = 50


def summary_to_wire(opp: Opportunity) -> dict:
    """The list/queue row: everything but the transcript and histories."""
    last = opp.messages[-1] if opp.messages else None
    return {
        "opportunity_id": opp.id,
        "customer_name": opp.customer_name,
        "state": opp.state.value,
        "product": opp.product.value,
        "signals": [s.value for s in opp.signals],
        "priority": opp.priority.value if opp.priority else None,
        "final_score": opp.final_score,
        "qualification": opp.qualification.value,
        "human_takeover": opp.human_takeover,
        "human_intervention_required": opp.human_intervention_required,
        "customer_message_count": opp.customer_message_count,
        "turns": opp.turns,
        "last_message_at": last.ts.isoformat() if last else None,
        "last_message_preview": last.text[:120] if last else None,
        "updated_at": opp.updated_at.isoformat(),
    }


def opportunity_to_wire(
    opp: Opportunity,
    *,
    messages: Optional[list[Message]] = None,
    case: Optional[HumanCase] = None,
    next_best_action=None,
    history_limit: int = DEFAULT_HISTORY_LIMIT,
) -> dict:
    transcript = opp.messages if messages is None else messages
    payload = {
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
        "expansion": list(opp.expansion),
        "last_intent": opp.last_intent.value,
        "best_intent": opp.best_intent.value,
        "urgency_observed": opp.urgency_observed,
        "priority": opp.priority.value if opp.priority else None,
        "final_score": opp.final_score,
        "score": _score_to_wire(opp.score),
        "fit": _fit_to_wire(opp.score),
        "behaviour": _behaviour_to_wire(opp.score),
        "qualification": opp.qualification.value,
        "qualification_reason": opp.qualification_reason,
        "solicitation_count": opp.solicitation_count,
        "score_history": [
            {"ts": e.timestamp.isoformat(), "score": e.score, "state": e.state, "trigger": e.trigger}
            for e in opp.score_history[-history_limit:]
        ],
        "state_history": [
            {"ts": e.timestamp.isoformat(), "from": e.from_state, "to": e.to_state, "reason": e.reason}
            for e in opp.state_history[-history_limit:]
        ],
        "history_limit": history_limit,
        "human_takeover": opp.human_takeover,
        "human_intervention_required": opp.human_intervention_required,
        "customer_message_count": opp.customer_message_count,
        "turns": opp.turns,
        "messages": [message_to_wire(m) for m in transcript],
        "case": case_to_wire(case) if case else None,
        "created_at": opp.created_at.isoformat(),
        "updated_at": opp.updated_at.isoformat(),
    }
    if next_best_action is not None:
        payload["next_best_action"] = {
            "action": next_best_action.action,
            "reason": next_best_action.reason,
            "priority": next_best_action.priority.value,
            "human_intervention_required": next_best_action.human_intervention_required,
        }
    return payload


def _score_to_wire(card: Optional[ScoreCard]) -> Optional[dict]:
    if card is None:
        return None
    return {
        "purchase_intent": card.purchase_intent,
        "purchase_readiness": card.purchase_readiness,
        "product_potential": card.product_potential,
        "expansion": card.expansion,
        "engagement": card.engagement,
        "total": card.total,
        "priority": card.priority.value,
    }


def _fit_to_wire(card: Optional[ScoreCard]) -> Optional[dict]:
    if card is None:
        return None
    return {
        "need_identified": card.need_identified,
        "product_potential": card.product_potential,
        "expansion": card.expansion,
        "total": card.fit_total,
    }


def _behaviour_to_wire(card: Optional[ScoreCard]) -> Optional[dict]:
    if card is None:
        return None
    return {
        "purchase_intent": card.purchase_intent,
        "purchase_readiness": card.purchase_readiness,
        "engagement": card.engagement,
        "engagement_depth": card.engagement_depth,
        "engagement_urgency": card.engagement_urgency,
        "engagement_recency": card.engagement_recency,
        "raw": card.behaviour_raw,
        "total": card.behaviour_total,
    }
