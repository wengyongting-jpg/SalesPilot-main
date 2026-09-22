# -*- coding: utf-8 -*-
"""Repository abstraction shared by the in-memory and SQLite implementations."""
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from ..models import HumanCase, Opportunity


class BaseRepository(ABC):
    def __init__(self) -> None:
        # P0-5: idempotency receipts, keyed by (opportunity_id,
        # client_message_id). Holds the serialised response of the request that
        # first used the key, so a replay can be answered without re-running the
        # pipeline. The default store is in-process; SqliteRepository overrides
        # it with a table so deduplication survives a restart.
        self._message_receipts: dict[tuple[str, str], dict] = {}

    # ---- Opportunities ---------------------------------------------------

    @abstractmethod
    def upsert_opportunity(self, opp: Opportunity) -> None: ...

    @abstractmethod
    def get_opportunity(self, opp_id: str) -> Optional[Opportunity]: ...

    @abstractmethod
    def list_opportunities(self) -> list[Opportunity]: ...

    @abstractmethod
    def delete_opportunity(self, opp_id: str) -> None: ...

    # ---- HITL cases ------------------------------------------------------

    @abstractmethod
    def add_case(self, case: HumanCase) -> None: ...

    def update_case(self, case: HumanCase) -> None:
        """Update a case (status transition). Default: same as add_case."""
        self.add_case(case)

    @abstractmethod
    def list_cases(self) -> list[HumanCase]: ...

    # ---- Idempotency receipts (P0-5) ------------------------------------

    def get_message_receipt(
        self, opportunity_id: str, client_message_id: str
    ) -> Optional[dict]:
        """Return the stored response for a replayed key, or None if unseen."""
        return self._message_receipts.get((opportunity_id, client_message_id))

    def save_message_receipt(
        self, opportunity_id: str, client_message_id: str, response: dict
    ) -> None:
        """Record the response produced for a client idempotency key."""
        self._message_receipts[(opportunity_id, client_message_id)] = response

    # ---- Optional persistence hook --------------------------------------

    def save(self, path: Optional[Path] = None) -> Path:  # pragma: no cover
        raise NotImplementedError("This repository does not support JSON export")
