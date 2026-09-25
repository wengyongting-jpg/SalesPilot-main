# -*- coding: utf-8 -*-
"""Opportunity reads and the one destructive write the API needs.

`api` may not import `kernel` and may not call a repository write method,
so the recommendation shown on the admin surface and the conversation reset
both come through here.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from ..domain.detection import Detection
from ..domain.enums import Qualification
from ..domain.message import Message
from ..domain.opportunity import Opportunity
from ..kernel import next_best_action, scoring
from ..kernel.next_best_action import NextBestAction
from ..storage.base import Repository
from . import InvalidCursor, OpportunityNotFound


def require(repo: Repository, opportunity_id: str) -> Opportunity:
    opp = repo.get_opportunity(opportunity_id)
    if opp is None:
        raise OpportunityNotFound(opportunity_id)
    return opp


def reset(repo: Repository, opportunity_id: str) -> bool:
    """Delete a conversation. Idempotent: an unknown id is a no-op, not an error."""
    return repo.delete_opportunity(opportunity_id)


def current_next_best_action(opp: Opportunity) -> NextBestAction:
    """What a representative should do now, from the stored profile alone."""
    return next_best_action.recommend(opp, Detection(), escalated=opp.human_takeover)


def score_explanation(opp: Opportunity) -> dict:
    """The audit trail behind the opportunity's current score and priority."""
    return scoring.explain(opp)


def held(repo: Repository) -> list[Opportunity]:
    """The review queue: conversations the machine put on hold (contract item 13)."""
    return [o for o in repo.list_opportunities() if o.qualification is Qualification.HELD]


def messages_since(opp: Opportunity, cursor: Optional[str]) -> list[Message]:
    """Messages newer than `cursor`: an ISO-8601 timestamp or a message id.

    No cursor returns the full transcript. A future timestamp or the last
    message's id returns nothing. Anything else raises `InvalidCursor`.
    """
    if not cursor:
        return list(opp.messages)
    for index, message in enumerate(opp.messages):
        if message.id == cursor:
            return list(opp.messages[index + 1 :])
    try:
        stamp = datetime.fromisoformat(cursor)
    except ValueError:
        raise InvalidCursor(cursor) from None
    if stamp.tzinfo is not None:
        stamp = stamp.replace(tzinfo=None)
    return [m for m in opp.messages if _naive(m.ts) > stamp]


def _naive(value: datetime) -> datetime:
    return value.replace(tzinfo=None) if value.tzinfo is not None else value
