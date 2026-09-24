# -*- coding: utf-8 -*-
"""Customer-tier request and response models.

**These models have no field in which sales intelligence could be placed.**

`docs/v0.0/api/interface-v1.md` §2: the visibility boundary is enforced server-side by
payload shape, not by client discipline. The frozen build returned the score, the
priority, the signals, the state, the next best action and the case to whoever called
the customer endpoint, and relied on the customer frontend to discard them. That is not
a boundary — the data arrived in the customer's browser and was readable in developer
tools.

So the projection is not a filter with a deny-list, which the next careless
`**payload` would defeat. It is a type with an allow-list and `extra="forbid"`, so
assigning a score raises rather than shipping.

What the customer legitimately gets: the reply, the approved knowledge-base facts that
their product cards are built from, quick replies, whether a human has taken over, and
their own idempotency key echoed back.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

_STRICT = ConfigDict(extra="forbid")


class IncomingMessage(BaseModel):
    model_config = _STRICT

    customer_name: str = Field(..., min_length=1)
    text: str = Field(..., min_length=1)
    customer_id: str = ""
    # Optional idempotency key. Replaying it returns the stored response without
    # re-running the pipeline, which is what makes a retry after a timeout safe.
    client_message_id: Optional[str] = None


class CustomerMessage(BaseModel):
    """One transcript entry, on the three axes a customer may see.

    `generation` is here deliberately: a template reply involved no model at all, and
    a reader must never be led to believe otherwise (`interface-v1.md` §5.7).
    """

    model_config = _STRICT

    id: str
    ts: Optional[str]
    role: str
    author: Optional[str]
    # Present only for messages written by a human representative. This is safe
    # customer-facing identity, not sales intelligence.
    rep_name: Optional[str]
    generation: Optional[str]
    text: str
    client_message_id: Optional[str]


class QuickReply(BaseModel):
    model_config = _STRICT

    id: str
    label: str


class CustomerQuestionOption(BaseModel):
    model_config = _STRICT
    id: str
    label: str


class CustomerQuestion(BaseModel):
    model_config = _STRICT
    field: str
    prompt: str
    options: list[CustomerQuestionOption]
    allow_other: bool


class CustomerReply(BaseModel):
    """The response to `POST /api/messages`.

    Note what is absent and cannot be added without editing this class: state, score,
    priority, signals, next best action, case internals, retrieval confidence, and
    every field of the agent run.
    """

    model_config = _STRICT

    reply: str
    human_takeover: bool
    message: Optional[CustomerMessage] = None
    # The approved knowledge-base facts, as a structured array. Never collapsed into
    # one prose string: the product cards are built from the individual entries.
    facts: list[str] = Field(default_factory=list)
    quick_replies: list[QuickReply] = Field(default_factory=list)
    customer_question: Optional[CustomerQuestion] = None
    client_message_id: Optional[str] = None


class CustomerTranscript(BaseModel):
    model_config = _STRICT

    conversation_id: str
    human_takeover: bool
    messages: list[CustomerMessage] = Field(default_factory=list)
    quick_replies: list[QuickReply] = Field(default_factory=list)
    customer_question: Optional[CustomerQuestion] = None


class ResetResult(BaseModel):
    model_config = _STRICT

    deleted: bool
    conversation_id: str


# ---- Projection ------------------------------------------------------------
# One function per response, reading from the service's canonical dictionary. Written
# as explicit field selection rather than `**payload` so that adding a field to the
# internal shape can never widen the customer surface by accident.


def project_reply(payload: dict) -> CustomerReply:
    opportunity = payload.get("opportunity") or {}
    message = payload.get("message")
    return CustomerReply(
        reply=payload.get("reply", ""),
        human_takeover=bool(opportunity.get("human_takeover", False)),
        message=project_message(message) if message else None,
        # `customer_facts`, not `retrieval.facts`: what the assistant was permitted to
        # say, so the product cards agree with the reply above them.
        facts=list(payload.get("customer_facts", [])),
        quick_replies=[
            QuickReply(id=chip["id"], label=chip["label"])
            for chip in payload.get("quick_replies", [])
        ],
        customer_question=payload.get("customer_question"),
        client_message_id=payload.get("client_message_id"),
    )


def project_message(message: dict) -> CustomerMessage:
    return CustomerMessage(
        id=message["id"],
        ts=message.get("ts"),
        role=message["role"],
        author=message.get("author"),
        rep_name=message.get("rep_name"),
        generation=message.get("generation"),
        text=message["text"],
        client_message_id=message.get("client_message_id"),
    )
