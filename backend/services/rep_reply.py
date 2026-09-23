# -*- coding: utf-8 -*-
"""A representative's own message — `interface-v1.md` §5.4.

Appended as `role=business, author=human, generation=human` and nothing else
happens: no extraction, no scoring, no state transition, no HITL, no run
record. A person talking to a customer is not an agent run. Refused when
nobody has taken the conversation over, because a human message on an
AI-owned conversation would be indistinguishable from the AI to the customer.
"""
from __future__ import annotations

from typing import Optional

from ..domain.message import Message
from ..storage.base import Repository
from . import NotUnderTakeover, OpportunityNotFound


def append_rep_reply(
    repo: Repository,
    opportunity_id: str,
    *,
    text: str,
    rep_name: Optional[str] = None,
    client_message_id: Optional[str] = None,
) -> Message:
    opp = repo.get_opportunity(opportunity_id)
    if opp is None:
        raise OpportunityNotFound(opportunity_id)
    if not opp.human_takeover:
        raise NotUnderTakeover(opportunity_id)
    message = Message.from_human(text, rep_name=rep_name, client_message_id=client_message_id)
    opp.messages.append(message)
    repo.upsert_opportunity(opp)
    return message
