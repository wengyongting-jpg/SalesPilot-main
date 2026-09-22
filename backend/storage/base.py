# -*- coding: utf-8 -*-
"""The repository contract, and the cursor parsing both implementations share.

One protocol, two implementations, and a parity test suite that runs every
behavioural assertion against both. That arrangement is what makes it honest for the
rest of the suite to use the in-memory repository for speed: if the two ever diverge,
the parity tests fail rather than the substitution quietly becoming a lie.

Only `backend.services` writes through these. Nothing else in the tree may.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional, Protocol, runtime_checkable

from ..domain.case import HumanCase
from ..domain.message import Message
from ..domain.opportunity import Opportunity


@runtime_checkable
class Repository(Protocol):
    # ---- Opportunities ---------------------------------------------------

    def upsert_opportunity(self, opp: Opportunity) -> None: ...

    def get_opportunity(
        self, opp_id: str, *, history_limit: Optional[int] = None
    ) -> Optional[Opportunity]:
        """Load one opportunity.

        `history_limit` bounds the score and state histories, keeping the most recent
        entries. Unbounded histories make an admin poll grow with the conversation —
        gap register item 12.
        """

    def list_opportunities(self) -> list[Opportunity]: ...

    def delete_opportunity(self, opp_id: str) -> None: ...

    def messages_since(
        self, opp_id: str, *, cursor: Optional[str] = None
    ) -> list[Message]:
        """Messages newer than `cursor`, which may be a message id or a timestamp.

        No cursor means the whole transcript. An unparsable cursor raises `ValueError`
        rather than falling back to everything: a client sending a malformed cursor
        would otherwise look healthy while re-transferring the transcript every poll.
        """

    # ---- Human cases -----------------------------------------------------

    def add_case(self, case: HumanCase) -> None: ...

    def update_case(self, case: HumanCase) -> None: ...

    def get_case(self, case_id: str) -> Optional[HumanCase]: ...

    def list_cases(self) -> list[HumanCase]: ...

    def active_case_for(self, opp_id: str) -> Optional[HumanCase]:
        """The open or taken-over case for this opportunity, if any.

        One active case per opportunity: a new escalation reason updates the existing
        case rather than opening a second, so a queue never shows a customer twice.
        """

    # ---- Idempotency receipts -------------------------------------------

    def get_message_receipt(
        self, opp_id: str, client_message_id: str
    ) -> Optional[dict]: ...

    def save_message_receipt(
        self, opp_id: str, client_message_id: str, response: dict
    ) -> None: ...

    # ---- Agent runs ------------------------------------------------------

    def save_agent_run(self, run: Any) -> None: ...

    def get_agent_run(self, run_id: str) -> Optional[dict]: ...

    def list_agent_runs(
        self,
        opp_id: str,
        *,
        client_message_id: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[dict]:
        """Runs for one conversation, newest first."""

    def conversation_totals(self, opp_id: str) -> dict:
        """Token and cost totals across every run of one conversation."""

    # ---- Lifecycle -------------------------------------------------------

    def close(self) -> None: ...


class MalformedCursor(ValueError):
    """The `since` cursor was neither a known message id nor a timestamp."""


def resolve_cursor(cursor: Optional[str], messages: list[Message]) -> int:
    """Return the index after which messages should be returned.

    Accepts a message id or an ISO-8601 timestamp, because the customer app knows the
    id of the last message it rendered while a poller may only have a clock. A cursor
    that is neither is an error, not a reason to return everything.
    """
    if cursor is None or cursor == "":
        return -1

    for index, message in enumerate(messages):
        if message.id == cursor:
            return index

    try:
        moment = datetime.fromisoformat(cursor)
    except ValueError as error:
        raise MalformedCursor(
            f"cursor {cursor!r} is neither a known message id nor an ISO-8601 "
            "timestamp"
        ) from error

    last_older = -1
    for index, message in enumerate(messages):
        if message.ts is not None and message.ts <= moment:
            last_older = index
    return last_older


def bound_history(entries: list, limit: Optional[int]) -> list:
    """Keep the most recent `limit` entries, or all of them."""
    if limit is None or limit <= 0 or len(entries) <= limit:
        return list(entries)
    return list(entries[-limit:])
