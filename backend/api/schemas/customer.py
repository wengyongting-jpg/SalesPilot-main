# -*- coding: utf-8 -*-
"""The customer tier's response models — deliberately incapable of leaking.

`interface-v1.md` §2 lists what a customer must never receive: opportunity
state, any score dimension, priority, signals, next best action, case
internals, retrieval confidence, agent-run telemetry. None of those has a
field here. The boundary is the type: a route declared with one of these as
its `response_model` cannot emit a key the model does not define, so a leak
becomes impossible rather than discouraged (`docs/backend-plan.md` §4 rule 4).

Pydantic drops unknown keys when a model is built from a dict, which is what
lets a replayed idempotency receipt (which carries internal fields for the
admin tier) and a fresh turn go through the same model unchanged.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class IncomingMessage(BaseModel):
    customer_id: str = ""
    customer_name: str = Field(..., min_length=1)
    text: str = Field(..., min_length=1)
    client_message_id: Optional[str] = None


class QuickReplyOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    label: str


class CustomerReply(BaseModel):
    """`POST /api/messages` — interface-v1 §5.1, plus `generation` (§5.7) and
    the product the reply is about (for the product card)."""

    model_config = ConfigDict(extra="ignore")

    reply: str
    generation: Optional[str] = None
    product: Optional[str] = None
    facts: list[str] = Field(default_factory=list)
    quick_replies: list[QuickReplyOut] = Field(default_factory=list)
    client_message_id: Optional[str] = None
    human_takeover: bool = False


class CustomerMessage(BaseModel):
    """One transcript entry — §5.1's safe transcript, with the stable `id`
    (contract item 5) and `generation` (§5.7)."""

    model_config = ConfigDict(extra="ignore")

    id: str
    ts: str
    role: str
    author: Optional[str] = None
    generation: Optional[str] = None
    text: str
    client_message_id: Optional[str] = None


class CustomerTranscript(BaseModel):
    model_config = ConfigDict(extra="ignore")

    opportunity_id: str
    human_takeover: bool
    messages: list[CustomerMessage]


class ResetResult(BaseModel):
    deleted: bool
    opportunity_id: str
