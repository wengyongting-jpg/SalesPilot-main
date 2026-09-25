# -*- coding: utf-8 -*-
"""Domain objects ⇄ plain dicts, for persistence.

Round-trips must be exact: `Message.id` and `Message.ts` are preserved as
stored (contract item 5: ids stable across reads), enums travel by `.value`,
datetimes as ISO-8601 text. This is the *storage* shape; the wire shapes the
API serves are P6's and derive from the domain separately.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from ..domain.case import HumanCase
from ..domain.decision import ActionKind, ActionStatus, PendingAction
from ..domain.detection import BuyingPosture, EvidenceQuality, ObservationEvidence
from ..domain.enums import (
    CaseStatus,
    Generation,
    Intent,
    MessageAuthor,
    MessageRole,
    OpportunityState,
    Priority,
    Product,
    Qualification,
    Signal,
)
from ..domain.message import Message
from ..domain.opportunity import Opportunity, ScoreCard, ScoreHistoryEntry, StateHistoryEntry


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value is not None else None


def _dt(value: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(value) if value else None


# ---- Message --------------------------------------------------------------------


def message_to_dict(message: Message) -> dict[str, Any]:
    return {
        "id": message.id,
        "role": message.role.value,
        "text": message.text,
        "ts": _iso(message.ts),
        "author": message.author_value,
        "generation": message.generation_value,
        "rep_name": message.rep_name,
        "client_message_id": message.client_message_id,
    }


def message_from_dict(data: dict[str, Any]) -> Message:
    return Message(
        role=MessageRole(data["role"]),
        text=data["text"],
        id=data["id"],
        ts=_dt(data["ts"]),
        author=MessageAuthor(data["author"]) if data.get("author") else None,
        generation=Generation(data["generation"]) if data.get("generation") else None,
        rep_name=data.get("rep_name"),
        client_message_id=data.get("client_message_id"),
    )


# ---- ScoreCard and histories ------------------------------------------------


def scorecard_to_dict(card: ScoreCard) -> dict[str, Any]:
    payload = {name: getattr(card, name) for name in ScoreCard.__dataclass_fields__}
    payload["priority"] = card.priority.value
    return payload


def scorecard_from_dict(data: dict[str, Any]) -> ScoreCard:
    values = dict(data)
    values["priority"] = Priority(values["priority"])
    return ScoreCard(**values)


def _score_entry_to_dict(entry: ScoreHistoryEntry) -> dict[str, Any]:
    return {
        "ts": _iso(entry.timestamp),
        "score": entry.score,
        "state": entry.state,
        "trigger": entry.trigger,
        "evidence": dict(entry.evidence),
    }


def _score_entry_from_dict(data: dict[str, Any]) -> ScoreHistoryEntry:
    return ScoreHistoryEntry(
        timestamp=_dt(data["ts"]),
        score=data["score"],
        state=data["state"],
        trigger=data["trigger"],
        evidence=dict(data.get("evidence", {})),
    )


def _state_entry_to_dict(entry: StateHistoryEntry) -> dict[str, Any]:
    return {
        "ts": _iso(entry.timestamp),
        "from": entry.from_state,
        "to": entry.to_state,
        "reason": entry.reason,
    }


def _state_entry_from_dict(data: dict[str, Any]) -> StateHistoryEntry:
    return StateHistoryEntry(
        timestamp=_dt(data["ts"]), from_state=data["from"], to_state=data["to"], reason=data["reason"]
    )


# ---- Opportunity ----------------------------------------------------------------


def opportunity_to_dict(opp: Opportunity) -> dict[str, Any]:
    pending = opp.pending_action
    if pending is None and opp.pending_handoff_reason:
        pending = PendingAction(
            kind=ActionKind.HANDOFF,
            reason_code="legacy_handoff",
            reason=opp.pending_handoff_reason,
            originating_customer_message_id=None,
            originating_assistant_message_id=None,
            status=ActionStatus.PENDING,
            created_at=opp.updated_at,
        )
    return {
        "id": opp.id,
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
        "customer_message_count": opp.customer_message_count,
        "score": scorecard_to_dict(opp.score) if opp.score else None,
        "score_history": [_score_entry_to_dict(e) for e in opp.score_history],
        "state_history": [_state_entry_to_dict(e) for e in opp.state_history],
        "human_takeover": opp.human_takeover,
        "human_intervention_required": opp.human_intervention_required,
        "pending_handoff_reason": opp.pending_handoff_reason,
        "pending_action": ({
            "kind": pending.kind.value,
            "reason_code": pending.reason_code,
            "reason": pending.reason,
            "originating_customer_message_id": pending.originating_customer_message_id,
            "originating_assistant_message_id": pending.originating_assistant_message_id,
            "status": pending.status.value,
            "created_at": _iso(pending.created_at),
        } if pending else None),
        "buying_posture": opp.buying_posture.value,
        "posture_evidence": [
            {"source_message_ids": list(e.source_message_ids), "span": e.span,
             "quality": e.quality.value}
            for e in opp.posture_evidence
        ],
        "pending_question_field": opp.pending_question_field,
        "collected_answers": dict(opp.collected_answers),
        "evidence_sources": dict(opp.evidence_sources),
        "qualification": opp.qualification.value,
        "qualification_reason": opp.qualification_reason,
        "solicitation_count": opp.solicitation_count,
        "messages": [message_to_dict(m) for m in opp.messages],
        "created_at": _iso(opp.created_at),
        "updated_at": _iso(opp.updated_at),
    }


def opportunity_from_dict(data: dict[str, Any]) -> Opportunity:
    raw_action = data.get("pending_action")
    if raw_action:
        pending_action = PendingAction(
            kind=ActionKind(raw_action["kind"]),
            reason_code=raw_action.get("reason_code", "legacy_handoff"),
            reason=raw_action.get("reason", data.get("pending_handoff_reason") or ""),
            originating_customer_message_id=raw_action.get("originating_customer_message_id"),
            originating_assistant_message_id=raw_action.get("originating_assistant_message_id"),
            status=ActionStatus(raw_action.get("status", ActionStatus.PENDING.value)),
            created_at=_dt(raw_action.get("created_at")) or _dt(data.get("updated_at")),
        )
    elif data.get("pending_handoff_reason"):
        # Explicit lazy migration for v1 payloads written before typed actions.
        pending_action = PendingAction(
            kind=ActionKind.HANDOFF,
            reason_code="legacy_handoff",
            reason=data["pending_handoff_reason"],
            originating_customer_message_id=None,
            originating_assistant_message_id=None,
            status=ActionStatus.PENDING,
            created_at=_dt(data.get("updated_at")),
        )
    else:
        pending_action = None
    legacy_pending_reason = data.get("pending_handoff_reason")
    if (
        not legacy_pending_reason and pending_action
        and pending_action.kind is ActionKind.HANDOFF
        and pending_action.status is ActionStatus.PENDING
    ):
        legacy_pending_reason = pending_action.reason
    return Opportunity(
        id=data["id"],
        customer_name=data["customer_name"],
        state=OpportunityState(data["state"]),
        product=Product(data["product"]),
        signals=[Signal(s) for s in data.get("signals", [])],
        signal_history=[Signal(s) for s in data.get("signal_history", [])],
        main_concern=data.get("main_concern"),
        competitive_risk=bool(data.get("competitive_risk", False)),
        churn_risk=bool(data.get("churn_risk", False)),
        compliance_risk=bool(data.get("compliance_risk", False)),
        expansion=list(data.get("expansion", [])),
        last_intent=Intent(data.get("last_intent", Intent.GENERIC.value)),
        best_intent=Intent(data.get("best_intent", Intent.GENERIC.value)),
        urgency_observed=bool(data.get("urgency_observed", False)),
        customer_message_count=int(data.get("customer_message_count", 0)),
        score=scorecard_from_dict(data["score"]) if data.get("score") else None,
        score_history=[_score_entry_from_dict(e) for e in data.get("score_history", [])],
        state_history=[_state_entry_from_dict(e) for e in data.get("state_history", [])],
        human_takeover=bool(data.get("human_takeover", False)),
        human_intervention_required=bool(data.get("human_intervention_required", False)),
        pending_handoff_reason=legacy_pending_reason,
        pending_action=pending_action,
        buying_posture=BuyingPosture(data.get("buying_posture", BuyingPosture.UNKNOWN.value)),
        posture_evidence=[
            ObservationEvidence(
                source_message_ids=list(e.get("source_message_ids", [])),
                span=e.get("span", ""),
                quality=EvidenceQuality(e.get("quality", EvidenceQuality.UNKNOWN.value)),
            ) for e in data.get("posture_evidence", [])
        ],
        pending_question_field=data.get("pending_question_field"),
        collected_answers=dict(data.get("collected_answers", {})),
        evidence_sources=dict(data.get("evidence_sources", {})),
        qualification=Qualification(data.get("qualification", Qualification.QUALIFIED.value)),
        qualification_reason=data.get("qualification_reason"),
        solicitation_count=int(data.get("solicitation_count", 0)),
        messages=[message_from_dict(m) for m in data.get("messages", [])],
        created_at=_dt(data["created_at"]),
        updated_at=_dt(data["updated_at"]),
    )


# ---- HumanCase --------------------------------------------------------------------


def case_to_dict(case: HumanCase) -> dict[str, Any]:
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
        "created_at": _iso(case.created_at),
    }


def case_from_dict(data: dict[str, Any]) -> HumanCase:
    return HumanCase(
        id=data["id"],
        opportunity_id=data["opportunity_id"],
        customer_name=data["customer_name"],
        state=OpportunityState(data["state"]),
        product=Product(data["product"]),
        reason=data["reason"],
        summary=data["summary"],
        recommended_action=data["recommended_action"],
        status=CaseStatus(data["status"]),
        created_at=_dt(data["created_at"]),
    )
