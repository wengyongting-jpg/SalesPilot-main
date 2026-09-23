# -*- coding: utf-8 -*-
"""The customer surface. `docs/api/interface-v1.md` §5.1.

Three endpoints, and every response goes through a projection in
`api.schemas.customer` that has no field for sales intelligence. The tier boundary is
the type, not the care taken here.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Request

from ...storage.base import MalformedCursor
from ...services.conversation import QuestionAnswerTooLong
from .. import errors
from ..deps import services_of
from ..schemas.customer import (
    CustomerReply,
    CustomerTranscript,
    IncomingMessage,
    QuickReply,
    ResetResult,
    project_message,
    project_reply,
)

router = APIRouter(tags=["customer"])


@router.post("/api/messages", response_model=CustomerReply)
def post_message(payload: IncomingMessage, request: Request) -> CustomerReply:
    """Process one customer message through the full pipeline.

    Supplying `client_message_id` makes the call idempotent: replaying the same key on
    the same conversation returns the stored response without re-running anything.
    Omitting it leaves the original non-idempotent behaviour, where a retry after a
    timeout would advance the message count and inflate the engagement evidence.
    """
    try:
        result = services_of(request).conversation.handle_customer_message(
            customer_id=payload.customer_id,
            customer_name=payload.customer_name,
            text=payload.text,
            client_message_id=payload.client_message_id,
        )
    except QuestionAnswerTooLong as error:
        raise errors.bad_request(str(error)) from error
    return project_reply(result.to_dict())


@router.get("/api/conversations/{conversation_id}", response_model=CustomerTranscript)
def get_conversation(
    conversation_id: str, request: Request, since: Optional[str] = None
) -> CustomerTranscript:
    """The transcript, optionally only what is newer than `since`.

    `since` accepts a message id or an ISO-8601 timestamp. A cursor that is neither is
    a 400 rather than a silent full read, because a client sending a malformed cursor
    would otherwise look healthy while re-transferring the whole transcript on every
    poll.
    """
    repo = services_of(request).repo
    opportunity = repo.get_opportunity(conversation_id, history_limit=0)
    if opportunity is None:
        raise errors.not_found("Conversation not found")

    try:
        messages = repo.messages_since(conversation_id, cursor=since)
    except MalformedCursor as error:
        raise errors.bad_request(str(error))

    from ...services.serialisation import message_to_dict, opportunity_to_dict

    return CustomerTranscript(
        conversation_id=conversation_id,
        human_takeover=opportunity.human_takeover,
        messages=[project_message(message_to_dict(m)) for m in messages],
        quick_replies=(
            [QuickReply(id="handoff_confirm", label="Confirm"),
             QuickReply(id="handoff_cancel", label="Cancel")]
            if opportunity.pending_handoff_reason else []
        ),
        customer_question=opportunity_to_dict(opportunity)["customer_question"],
    )


@router.delete("/api/conversations/{conversation_id}", response_model=ResetResult)
def reset_conversation(conversation_id: str, request: Request) -> ResetResult:
    """Reset a conversation. Idempotent, so a demo operator can press it twice."""
    existed = services_of(request).conversation.reset(conversation_id)
    return ResetResult(deleted=existed, conversation_id=conversation_id)
