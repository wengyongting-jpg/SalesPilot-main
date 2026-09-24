# -*- coding: utf-8 -*-
"""Wire pieces both tiers use: messages, cases, and the admin request bodies.

`message_to_wire` is the one place a message is serialised, so the role/
author/generation axes (`interface-v1.md` §5.7–5.8) are emitted identically
everywhere: `role` is only ever `"customer"` or `"business"`.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from ...domain.case import HumanCase
from ...domain.message import Message


def message_to_wire(message: Message) -> dict:
    return {
        "id": message.id,
        "ts": message.ts.isoformat(),
        "role": message.role.value,
        "author": message.author_value,
        "generation": message.generation_value,
        "text": message.text,
        "client_message_id": message.client_message_id,
        "rep_name": message.rep_name,
    }


def case_to_wire(case: HumanCase) -> dict:
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


class CaseStatusUpdate(BaseModel):
    status: str = Field(..., min_length=1)


class RepReplyIn(BaseModel):
    text: str = Field(..., min_length=1)
    rep_name: Optional[str] = None
    client_message_id: Optional[str] = None


class DisqualifyIn(BaseModel):
    reason: str = Field(..., min_length=1)


class ReleaseIn(BaseModel):
    reason: Optional[str] = None
