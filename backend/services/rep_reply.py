# -*- coding: utf-8 -*-
"""A human representative replying inside the console.

`interface-v1.md` §5.4. The original design treated human takeover as a **channel
switch** — the representative phoned the customer — which is why no write path for a
human message existed. The admin Inbox needs one, so this is that path, and it is
deliberately narrow.

What it does: appends one message attributed to a person.

What it does **not** do: run extraction, scoring, the state machine, or escalation.
The human is talking, not the agent. Advancing the opportunity's score because a
representative typed a sentence would attribute the customer's engagement to our own
staff, and the message count would stop counting what its name says.

Rejected with `NotUnderTakeover` when nobody owns the conversation, so the endpoint
cannot become a way to inject text while the assistant is still autonomously selling.
"""
from __future__ import annotations

from typing import Optional

from ..domain.message import Message
from ..observability.logging import get_logger


class RepReplyError(Exception):
    """Base class, so a caller can catch the family."""


class UnknownOpportunity(RepReplyError):
    """No such conversation."""


class NotUnderTakeover(RepReplyError):
    """Nobody has taken this conversation over, so a human reply is not expected."""


class RepReplyService:
    def __init__(self, repo) -> None:
        self.repo = repo
        self.logger = get_logger()

    def reply(
        self,
        opportunity_id: str,
        *,
        text: str,
        rep_name: Optional[str] = None,
        client_message_id: Optional[str] = None,
    ) -> Message:
        opp = self.repo.get_opportunity(opportunity_id)
        if opp is None:
            raise UnknownOpportunity(f"no conversation with id {opportunity_id!r}")

        if not opp.human_takeover:
            raise NotUnderTakeover(
                f"{opportunity_id} is not under human takeover; a representative "
                "reply is not accepted while the assistant is handling it"
            )

        if client_message_id:
            existing = self._already_sent(opp, client_message_id)
            if existing is not None:
                # Same reasoning as customer-message idempotency: a retry after a
                # timeout must not double-post to the customer.
                return existing

        message = Message.from_human(
            text.strip(), rep_name=rep_name, client_message_id=client_message_id
        )
        opp.messages.append(message)
        # Nothing else is touched. No count, no score, no state, no signals, no case.
        self.repo.upsert_opportunity(opp)

        self.logger.info(
            "rep reply | %s | by %s | %d chars",
            opportunity_id, rep_name or "unnamed", len(message.text),
        )
        return message

    @staticmethod
    def _already_sent(opp, client_message_id: str) -> Optional[Message]:
        for message in reversed(opp.messages):
            if message.client_message_id == client_message_id:
                return message
        return None
