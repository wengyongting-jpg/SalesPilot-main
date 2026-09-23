# -*- coding: utf-8 -*-
"""In-memory repository: the default for tests and `--demo`.

Stores live objects, as the frozen build's did. A caller that mutates an
object it fetched is mutating the stored one; `services` always writes back
through `upsert_opportunity` anyway, so the two backends behave the same.
"""
from __future__ import annotations

import copy
from datetime import datetime
from typing import Any, Optional

from ..domain.case import HumanCase
from ..domain.opportunity import Opportunity
from .base import Repository


class MemoryRepository(Repository):
    def __init__(self) -> None:
        self._opportunities: dict[str, Opportunity] = {}
        self._cases: dict[str, HumanCase] = {}
        self._receipts: dict[tuple[str, str], dict[str, Any]] = {}
        self._runs: list[dict[str, Any]] = []

    # ---- Opportunities ------------------------------------------------------

    def upsert_opportunity(self, opp: Opportunity) -> None:
        opp.updated_at = datetime.now()
        self._opportunities[opp.id] = opp

    def get_opportunity(self, opportunity_id: str) -> Optional[Opportunity]:
        return self._opportunities.get(opportunity_id)

    def list_opportunities(self) -> list[Opportunity]:
        return sorted(self._opportunities.values(), key=lambda o: o.updated_at)

    def delete_opportunity(self, opportunity_id: str) -> bool:
        return self._opportunities.pop(opportunity_id, None) is not None

    # ---- Cases ----------------------------------------------------------------

    def add_case(self, case: HumanCase) -> None:
        self._cases[case.id] = case

    def update_case(self, case: HumanCase) -> None:
        self._cases[case.id] = case

    def get_case(self, case_id: str) -> Optional[HumanCase]:
        return self._cases.get(case_id)

    def list_cases(self) -> list[HumanCase]:
        return sorted(self._cases.values(), key=lambda c: c.created_at)

    # ---- Idempotency receipts ----------------------------------------------

    def get_receipt(self, opportunity_id: str, client_message_id: str) -> Optional[dict[str, Any]]:
        document = self._receipts.get((opportunity_id, client_message_id))
        return copy.deepcopy(document) if document is not None else None

    def save_receipt(self, opportunity_id: str, client_message_id: str, document: dict[str, Any]) -> None:
        self._receipts[(opportunity_id, client_message_id)] = copy.deepcopy(document)

    # ---- Agent runs -----------------------------------------------------------

    def save_run(self, run: dict[str, Any]) -> None:
        self._runs.append(copy.deepcopy(run))

    def get_run(self, run_id: str) -> Optional[dict[str, Any]]:
        for run in self._runs:
            if run["run_id"] == run_id:
                return copy.deepcopy(run)
        return None

    def list_runs(
        self,
        *,
        opportunity_id: Optional[str] = None,
        client_message_id: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        selected = [
            run
            for run in reversed(self._runs)
            if (opportunity_id is None or run["opportunity_id"] == opportunity_id)
            and (client_message_id is None or run["client_message_id"] == client_message_id)
        ]
        return copy.deepcopy(selected[:limit])
