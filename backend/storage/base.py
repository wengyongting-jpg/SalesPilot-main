# -*- coding: utf-8 -*-
"""The repository contract both backends implement.

Four record kinds: opportunities, human cases, idempotency receipts and agent
runs. Agent runs are stored and returned as plain dicts — the record type
lives in `backend.observability`, which this package may not import
(`test_architecture.py`), and a persisted run is read back only to be served,
never re-computed.

Only `backend.services` calls the write methods. That is a rule the
architecture test enforces, not a convention.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

from ..domain.case import HumanCase
from ..domain.opportunity import Opportunity


class MalformedCursor(ValueError):
    """The `since` cursor was neither a known message id nor a timestamp."""


class Repository(ABC):
    # ---- Opportunities ------------------------------------------------------

    @abstractmethod
    def upsert_opportunity(self, opp: Opportunity) -> None: ...

    @abstractmethod
    def get_opportunity(
        self, opportunity_id: str, *, history_limit: Optional[int] = None
    ) -> Optional[Opportunity]: ...

    @abstractmethod
    def list_opportunities(self) -> list[Opportunity]: ...

    @abstractmethod
    def delete_opportunity(self, opportunity_id: str) -> bool: ...

    # ---- Cases ----------------------------------------------------------------

    @abstractmethod
    def add_case(self, case: HumanCase) -> None: ...

    @abstractmethod
    def update_case(self, case: HumanCase) -> None: ...

    @abstractmethod
    def get_case(self, case_id: str) -> Optional[HumanCase]: ...

    @abstractmethod
    def list_cases(self) -> list[HumanCase]: ...

    def active_case_for(self, opportunity_id: str) -> Optional[HumanCase]:
        """The one case a representative still owns for this opportunity, if any."""
        for case in self.list_cases():
            if case.opportunity_id == opportunity_id and case.is_active:
                return case
        return None

    # ---- Idempotency receipts ----------------------------------------------

    @abstractmethod
    def get_receipt(self, opportunity_id: str, client_message_id: str) -> Optional[dict[str, Any]]: ...

    @abstractmethod
    def save_receipt(self, opportunity_id: str, client_message_id: str, document: dict[str, Any]) -> None: ...

    # ---- Agent runs -----------------------------------------------------------

    @abstractmethod
    def save_run(self, run: dict[str, Any]) -> None: ...

    @abstractmethod
    def get_run(self, run_id: str) -> Optional[dict[str, Any]]: ...

    @abstractmethod
    def list_runs(
        self,
        *,
        opportunity_id: Optional[str] = None,
        client_message_id: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Newest first."""

    # ---- Lifecycle ----------------------------------------------------------------

    def close(self) -> None:
        return None
