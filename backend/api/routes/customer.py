# -*- coding: utf-8 -*-
"""The customer surface — `interface-v1.md` §5.1, §5.5, §5.6.

Every route here declares a `schemas.customer` response model. That is the
visibility boundary: whatever the service returns, only the fields those
models define can leave the process.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query

from ...services import opportunities
from ...services.conversation import ConversationService
from ...storage.base import Repository
from ..deps import get_repo, get_service
from ..schemas.customer import (
    CustomerMessage,
    CustomerReply,
    CustomerTranscript,
    IncomingMessage,
    ResetResult,
)
from ..schemas.shared import message_to_wire

router = APIRouter()


@router.post("/messages", response_model=CustomerReply)
def post_message(
    body: IncomingMessage, service: ConversationService = Depends(get_service)
) -> CustomerReply:
    result = service.handle_customer_message(
        body.customer_id,
        body.customer_name,
        body.text,
        client_message_id=body.client_message_id,
    )
    # A replay and a fresh turn take the same path: the receipt carries a few
    # admin-only keys and the model drops them.
    return CustomerReply.model_validate(result.receipt)


@router.get("/conversations/{opportunity_id}", response_model=CustomerTranscript)
def get_conversation(
    opportunity_id: str,
    since: Optional[str] = Query(default=None),
    repo: Repository = Depends(get_repo),
) -> CustomerTranscript:
    opp = opportunities.require(repo, opportunity_id)
    messages = opportunities.messages_since(opp, since)
    return CustomerTranscript(
        opportunity_id=opp.id,
        human_takeover=opp.human_takeover,
        messages=[CustomerMessage.model_validate(message_to_wire(m)) for m in messages],
    )


@router.delete("/conversations/{opportunity_id}", response_model=ResetResult)
def reset_conversation(opportunity_id: str, repo: Repository = Depends(get_repo)) -> ResetResult:
    return ResetResult(deleted=opportunities.reset(repo, opportunity_id), opportunity_id=opportunity_id)
