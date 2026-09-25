# -*- coding: utf-8 -*-
"""Internal, typed records for customer-action decisions.

These values are not part of interface v1. The legacy handoff-reason string is
still projected separately while the service migrates callers to this record.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

from .enums import Priority, ReplyMode


@dataclass
class NextBestAction:
    """The kernel's representative recommendation and customer-safe reply mode."""

    action: str
    reason: str
    priority: Priority
    reply_mode: ReplyMode = ReplyMode.ANSWER
    human_intervention_required: bool = False


class ActionKind(str, Enum):
    HANDOFF = "handoff"
    READINESS_INVITATION = "readiness_invitation"


class ActionStatus(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


class DecisionAction(str, Enum):
    ANSWER = "answer"
    CLARIFY = "clarify"
    OFFER_HANDOFF = "offer_handoff"
    CONFIRM_HANDOFF = "confirm_handoff"
    CANCEL_HANDOFF = "cancel_handoff"
    HOLD_FOR_STAFF = "hold_for_staff"
    CLEAR_PENDING_ACTION = "clear_pending_action"


@dataclass
class PendingAction:
    kind: ActionKind
    reason_code: str
    reason: str
    originating_customer_message_id: Optional[str]
    originating_assistant_message_id: Optional[str]
    status: ActionStatus
    created_at: datetime


@dataclass(frozen=True)
class Decision:
    action: DecisionAction
    reason_code: str
    reason: Optional[str] = None
    restrictions: tuple[str, ...] = ()
    evidence_message_ids: tuple[str, ...] = ()
