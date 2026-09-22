# -*- coding: utf-8 -*-
"""The canonical dictionary form of one conversation result.

**Not a tier projection.** This is the full, internal shape; `backend.api.schemas`
narrows it per visibility tier, and the customer schema has no field to put most of it
in. Keeping one canonical form here means an idempotency receipt and a live response
serialise through the same code, so a replay cannot drift from the original.
"""
from __future__ import annotations

from typing import Any, Optional

from ..domain.case import HumanCase
from ..domain.decision import NextBestAction
from ..domain.detection import Detection, RetrievalResult
from ..domain.message import Message
from ..domain.opportunity import Opportunity, ScoreCard


def result_to_dict(result) -> dict:
    return {
        "reply": result.reply,
        # The key of the *request* that produced this result. Recorded at the top
        # level because the customer's key belongs to their own message, not to the
        # reply — reading it off the reply returns null, which is how the first
        # version of the echo was silently wrong.
        "client_message_id": result.client_message_id,
        "message": message_to_dict(result.message) if result.message else None,
        "opportunity": opportunity_to_dict(result.opportunity),
        "detection": detection_to_dict(result.detection),
        "retrieval": retrieval_to_dict(result.retrieval),
        "score": score_to_dict(result.score),
        # What the assistant was permitted to say this turn. The customer tier returns
        # this, not `retrieval.facts` — a handover reply must not arrive with a price
        # card attached.
        "customer_facts": list(result.customer_facts),
        "state_change": result.state_change,
        "next_best_action": action_to_dict(result.next_best_action),
        "case": case_to_dict(result.case),
        "quick_replies": [
            {"id": chip.id, "label": chip.label} for chip in result.quick_replies
        ],
        "extraction_source": result.extraction_source,
        "agent_run": result.agent_run.to_dict() if result.agent_run else None,
    }


def message_to_dict(message: Message) -> dict:
    return {
        "id": message.id,
        "ts": message.ts.isoformat() if message.ts else None,
        "role": message.role.value,
        "author": message.author_value,
        "generation": message.generation_value,
        "rep_name": message.rep_name,
        "text": message.text,
        "client_message_id": message.client_message_id,
    }


def opportunity_to_dict(opp: Optional[Opportunity]) -> Optional[dict]:
    if opp is None:
        return None
    return {
        "opportunity_id": opp.id,
        "customer_name": opp.customer_name,
        "state": opp.state.value,
        "product": opp.product.value,
        "signals": [signal.value for signal in opp.signals],
        "signal_history": [signal.value for signal in opp.signal_history],
        "main_concern": opp.main_concern,
        "competitive_risk": opp.competitive_risk,
        "churn_risk": opp.churn_risk,
        "compliance_risk": opp.compliance_risk,
        "expansion": list(opp.expansion),
        "priority": opp.priority.value if opp.priority else None,
        "final_score": opp.final_score,
        # The full breakdown, not just the headline. Inspectability is the point of
        # the two-axis redesign: a reviewer who cannot decompose a number has no way
        # to sanity-check it, and "behaviour 29" is not reviewable while
        # "raw 82, decayed to 35% after forty days of silence" is.
        "score": score_to_dict(opp.score),
        "qualification": opp.qualification.value,
        "qualification_reason": opp.qualification_reason,
        # The truthful name, with the deprecated alias alongside it for the wire.
        # `interface-v1.md` §1.1.
        "customer_message_count": opp.customer_message_count,
        "turns": opp.turns,
        "human_takeover": opp.human_takeover,
        "human_intervention_required": opp.human_intervention_required,
        "score_history": [
            {
                "ts": entry.timestamp.isoformat(),
                "score": entry.score,
                "state": entry.state,
                "trigger": entry.trigger,
            }
            for entry in opp.score_history
        ],
        "state_history": [
            {
                "ts": entry.timestamp.isoformat(),
                "from": entry.from_state,
                "to": entry.to_state,
                "reason": entry.reason,
            }
            for entry in opp.state_history
        ],
        "messages": [message_to_dict(message) for message in opp.messages],
        "created_at": opp.created_at.isoformat(),
        "updated_at": opp.updated_at.isoformat(),
    }


def detection_to_dict(det: Optional[Detection]) -> Optional[dict]:
    if det is None:
        return None
    return {
        "intent": det.intent.value,
        "product": det.product.value,
        "signals": [signal.value for signal in det.signals],
        "concerns": list(det.concerns),
        "restricted": det.restricted,
        "cancellation": det.cancellation,
        "postponement": det.postponement,
        "genuine_enquiry": det.genuine_enquiry,
        "solicitation": det.solicitation,
    }


def retrieval_to_dict(retrieval: Optional[RetrievalResult]) -> Optional[dict]:
    if retrieval is None:
        return None
    return {
        # A structured array, never one prose string: the customer app builds product
        # cards from the individual entries.
        "facts": list(retrieval.facts),
        "confidence": retrieval.confidence,
        "product": retrieval.product.value,
    }


def score_to_dict(score: Optional[ScoreCard]) -> Optional[dict]:
    if score is None:
        return None
    return {
        "need_identified": score.need_identified,
        "product_potential": score.product_potential,
        "expansion": score.expansion,
        "fit_total": score.fit_total,
        "purchase_intent": score.purchase_intent,
        "purchase_readiness": score.purchase_readiness,
        "engagement": score.engagement,
        "engagement_depth": score.engagement_depth,
        "engagement_urgency": score.engagement_urgency,
        "engagement_recency": score.engagement_recency,
        "behaviour_raw": score.behaviour_raw,
        "behaviour_total": score.behaviour_total,
        # Display only. Ranking uses `priority`, which is a two-axis matrix rather
        # than a threshold on this number.
        "total": score.total,
        "priority": score.priority.value,
    }


def action_to_dict(action: Optional[NextBestAction]) -> Optional[dict]:
    if action is None:
        return None
    return {
        "action": action.action,
        "reason": action.reason,
        "priority": action.priority.value,
        "reply_mode": action.reply_mode.value,
        "human_intervention_required": action.human_intervention_required,
    }


def case_to_dict(case: Optional[HumanCase]) -> Optional[dict]:
    if case is None:
        return None
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
