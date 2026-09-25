# -*- coding: utf-8 -*-
"""Pure deterministic policy for replies to an explicit pending action."""
from __future__ import annotations

from typing import Optional

from ..domain.decision import (
    ActionKind, ActionStatus, Decision, DecisionAction, PendingAction,
)


def decide_pending_response(
    pending: Optional[PendingAction], text: str, *, current_message_id: Optional[str] = None,
) -> Optional[Decision]:
    """Resolve a short response only against one explicit pending prompt."""
    normal = " ".join(text.casefold().split()).strip(" .!?。！？")
    affirmative = normal in {
        "yes", "yeah", "yep", "ok", "okay", "sure", "confirm", "yes please",
        "please do", "go ahead", "i'm ready", "i’m ready", "i am ready",
        "yes i'm ready", "yes i’m ready", "yes im ready", "ready", "确认", "是", "好的",
    }
    negative = normal in {"no", "no thanks", "not now", "cancel", "取消", "否", "不用"}
    if pending is None or pending.status is not ActionStatus.PENDING:
        return (
            Decision(
                DecisionAction.CLARIFY, "unanchored_affirmative",
                evidence_message_ids=(current_message_id,) if current_message_id else (),
            )
            if affirmative else None
        )
    evidence = tuple(dict.fromkeys(
        item for item in (pending.originating_customer_message_id, current_message_id) if item
    ))
    if pending.kind is ActionKind.READINESS_INVITATION and affirmative:
        return Decision(DecisionAction.OFFER_HANDOFF, "sales_followup", pending.reason,
                        evidence_message_ids=evidence)
    if pending.kind is ActionKind.HANDOFF and affirmative:
        return Decision(DecisionAction.CONFIRM_HANDOFF, pending.reason_code, pending.reason,
                        evidence_message_ids=evidence)
    if negative:
        return Decision(DecisionAction.CANCEL_HANDOFF, pending.reason_code, pending.reason,
                        evidence_message_ids=evidence)
    return Decision(DecisionAction.CLEAR_PENDING_ACTION, pending.reason_code, pending.reason,
                    evidence_message_ids=evidence)
