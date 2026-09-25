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
from ..domain.enums import MessageRole, Qualification
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


def generate_staff_brief(repo: Repository, opportunity_id: str) -> Optional[dict]:
    """On-demand staff-only handoff brief, grounded in the stored conversation.

    `None` when there is no opportunity or no active case: a brief is for a
    representative about to pick up a handoff, not a general-purpose summary,
    so it is gated the same way a handoff itself is.

    Template-only wording, deliberately: this route composes the same
    grounded evidence a model-drafted brief would use, but does not invoke a
    model itself, so it carries no new cost, latency or failure mode. A
    model-drafted version is a separate, larger change if it is wanted later.
    """
    opp = repo.get_opportunity(opportunity_id)
    case = repo.active_case_for(opportunity_id)
    if opp is None or case is None:
        return None
    latest_customer = next(
        (m for m in reversed(opp.messages) if m.role is MessageRole.CUSTOMER), None,
    )
    evidence = {
        "need": opp.main_concern or "not yet established",
        "product": opp.product.value,
        "handoff_reason": case.reason,
        "priority": opp.priority.value if opp.priority else "unknown",
        "score": opp.final_score,
        "keywords": [signal.value for signal in opp.signals[:5]],
        "latest_message": latest_customer.text[:500] if latest_customer else "none",
        "latest_message_id": latest_customer.id if latest_customer else None,
    }
    text = (
        f"Need: {evidence['need']}\n"
        f"Product: {evidence['product']}\n"
        f"Handoff: {evidence['handoff_reason']}\n"
        f"Priority / score: {evidence['priority']} / {evidence['score']}\n"
        f"Keywords: {', '.join(evidence['keywords']) or 'none yet'}\n"
        f"Latest customer message: {evidence['latest_message']}\n"
        "Next step: Review the transcript, verify details and contact the customer."
    )
    return {"text": text, "source": "template", "evidence": evidence, "usage": None}


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
