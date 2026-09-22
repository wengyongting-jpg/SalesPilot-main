# -*- coding: utf-8 -*-
"""In-memory repository: process lifetime, no file, no schema.

Used by the test suite and by `--demo`. It deep-copies on the way in and out, which
is the detail that makes it a faithful stand-in: a caller mutating a returned
opportunity must not silently change the store, because with SQLite it would not.
Without that copy every test using this repository would be measuring something the
real system does not do.
"""
from __future__ import annotations

import copy
from typing import Any, Optional

from ..domain.case import HumanCase
from ..domain.enums import CaseStatus
from ..domain.message import Message
from ..domain.opportunity import Opportunity
from .base import bound_history, resolve_cursor


class InMemoryRepository:
    def __init__(self) -> None:
        self._opportunities: dict[str, Opportunity] = {}
        self._cases: dict[str, HumanCase] = {}
        self._receipts: dict[tuple[str, str], dict] = {}
        self._runs: dict[str, dict] = {}
        # Insertion order, so "newest first" means the same thing here as it does
        # against a database ordered by its timestamp.
        self._run_order: list[str] = []

    # ---- Opportunities ---------------------------------------------------

    def upsert_opportunity(self, opp: Opportunity) -> None:
        self._opportunities[opp.id] = copy.deepcopy(opp)

    def get_opportunity(
        self, opp_id: str, *, history_limit: Optional[int] = None
    ) -> Optional[Opportunity]:
        stored = self._opportunities.get(opp_id)
        if stored is None:
            return None
        loaded = copy.deepcopy(stored)
        loaded.score_history = bound_history(loaded.score_history, history_limit)
        loaded.state_history = bound_history(loaded.state_history, history_limit)
        return loaded

    def list_opportunities(self) -> list[Opportunity]:
        return [copy.deepcopy(opp) for opp in self._opportunities.values()]

    def delete_opportunity(self, opp_id: str) -> None:
        self._opportunities.pop(opp_id, None)

    def messages_since(
        self, opp_id: str, *, cursor: Optional[str] = None
    ) -> list[Message]:
        stored = self._opportunities.get(opp_id)
        if stored is None:
            return []
        messages = stored.messages
        after = resolve_cursor(cursor, messages)
        return [copy.deepcopy(message) for message in messages[after + 1:]]

    # ---- Human cases -----------------------------------------------------

    def add_case(self, case: HumanCase) -> None:
        self._cases[case.id] = copy.deepcopy(case)

    def update_case(self, case: HumanCase) -> None:
        self._cases[case.id] = copy.deepcopy(case)

    def get_case(self, case_id: str) -> Optional[HumanCase]:
        stored = self._cases.get(case_id)
        return copy.deepcopy(stored) if stored else None

    def list_cases(self) -> list[HumanCase]:
        return [copy.deepcopy(case) for case in self._cases.values()]

    def active_case_for(self, opp_id: str) -> Optional[HumanCase]:
        for case in self._cases.values():
            if case.opportunity_id == opp_id and case.status is not CaseStatus.CLOSED:
                return copy.deepcopy(case)
        return None

    # ---- Idempotency receipts -------------------------------------------

    def get_message_receipt(
        self, opp_id: str, client_message_id: str
    ) -> Optional[dict]:
        stored = self._receipts.get((opp_id, client_message_id))
        return copy.deepcopy(stored) if stored is not None else None

    def save_message_receipt(
        self, opp_id: str, client_message_id: str, response: dict
    ) -> None:
        self._receipts[(opp_id, client_message_id)] = copy.deepcopy(response)

    # ---- Agent runs ------------------------------------------------------

    def save_agent_run(self, run: Any) -> None:
        payload = run.to_dict() if hasattr(run, "to_dict") else dict(run)
        run_id = payload["run_id"]
        if run_id not in self._runs:
            self._run_order.append(run_id)
        self._runs[run_id] = payload

    def get_agent_run(self, run_id: str) -> Optional[dict]:
        stored = self._runs.get(run_id)
        return copy.deepcopy(stored) if stored else None

    def list_agent_runs(
        self,
        opp_id: str,
        *,
        client_message_id: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[dict]:
        found = []
        for run_id in reversed(self._run_order):
            payload = self._runs[run_id]
            if payload.get("opportunity_id") != opp_id:
                continue
            if (
                client_message_id is not None
                and payload.get("client_message_id") != client_message_id
            ):
                continue
            found.append(copy.deepcopy(payload))
            if limit is not None and len(found) >= limit:
                break
        return found

    def conversation_totals(self, opp_id: str) -> dict:
        runs = self.list_agent_runs(opp_id)
        tokens = sum(run["totals"]["total_tokens"] for run in runs)
        amount = sum(run["totals"]["cost"]["amount"] for run in runs)
        known = all(run["totals"]["cost"]["pricing_known"] for run in runs)
        return {
            "opportunity_id": opp_id,
            "run_count": len(runs),
            "total_tokens": tokens,
            "cost": {
                "amount": round(amount, 8),
                "currency": "USD",
                "pricing_known": known if runs else True,
            },
        }

    # ---- Lifecycle -------------------------------------------------------

    def close(self) -> None:
        """Nothing to release. Present so both implementations share one protocol."""
