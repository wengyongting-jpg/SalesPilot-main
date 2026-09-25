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


class InMemoryRepository(Repository):
    def __init__(self) -> None:
        self._opportunities: dict[str, Opportunity] = {}
        self._cases: dict[str, HumanCase] = {}
        self._receipts: dict[tuple[str, str], dict[str, Any]] = {}
        self._runs: list[dict[str, Any]] = []
        self._memory: dict[str, dict[str, Any]] = {}

    # ---- Opportunities ------------------------------------------------------

    def upsert_opportunity(self, opp: Opportunity) -> None:
        opp.updated_at = datetime.now()
        self._opportunities[opp.id] = opp

    def get_opportunity(
        self, opportunity_id: str, *, history_limit: Optional[int] = None
    ) -> Optional[Opportunity]:
        opp = self._opportunities.get(opportunity_id)
        if opp and history_limit is not None:
            # A bounded read is a view; trimming it must not mutate stored data.
            opp = copy.deepcopy(opp)
            # Trim history if requested
            if history_limit <= 0:
                opp.score_history = []
                opp.state_history = []
            else:
                opp.score_history = opp.score_history[-history_limit:] if opp.score_history else []
                opp.state_history = opp.state_history[-history_limit:] if opp.state_history else []
        return opp

    def list_opportunities(self) -> list[Opportunity]:
        return sorted(self._opportunities.values(), key=lambda o: o.updated_at)

    def get_memory(self, opportunity_id: str) -> Optional[dict[str, Any]]:
        value = self._memory.get(opportunity_id)
        return copy.deepcopy(value) if value is not None else None

    def search_messages(
        self, opportunity_id: str, query: str, *, limit: int = 3
    ) -> list[dict[str, Any]]:
        needle = " ".join(str(query).casefold().split())[:120]
        if not needle:
            return []
        opportunity = self._opportunities.get(opportunity_id)
        if opportunity is None:
            return []
        matches = []
        for _, message in reversed(list(enumerate(opportunity.messages))):
            if needle in " ".join(message.text.casefold().split()):
                matches.append({
                    "message_id": message.id,
                    "role": message.role.value,
                    "timestamp": message.ts.isoformat(),
                    "text": message.text,
                })
                if len(matches) >= max(1, min(int(limit), 5)):
                    break
        return matches

    def delete_opportunity(self, opportunity_id: str) -> bool:
        self._memory.pop(opportunity_id, None)
        # Cases and idempotency receipts are keyed by opportunity id, not by a
        # foreign key SQLite would cascade for us, so a reset that leaves them
        # behind orphans them: a stale case still shows "Taken Over" for a
        # conversation that no longer exists, and a stale receipt makes the
        # *next* customer message reusing the same client_message_id (a fresh
        # conversation started with the same customer id) try to replay a
        # reply from an opportunity that is no longer there.
        stale_case_ids = [
            case_id for case_id, case in self._cases.items()
            if case.opportunity_id == opportunity_id
        ]
        for case_id in stale_case_ids:
            del self._cases[case_id]
        stale_receipt_keys = [
            key for key in self._receipts if key[0] == opportunity_id
        ]
        for key in stale_receipt_keys:
            del self._receipts[key]
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

    def save_turn(
        self,
        opportunity: Opportunity,
        run: dict[str, Any],
        *,
        case: Optional[HumanCase] = None,
        receipt: Optional[dict[str, Any]] = None,
        memory: Optional[dict[str, Any]] = None,
    ) -> None:
        """Validate and copy payload values before publishing any turn records."""
        stored_opportunity = opportunity
        stored_case = case
        stored_run = copy.deepcopy(run)
        stored_receipt = copy.deepcopy(receipt) if receipt is not None else None
        key = None
        if stored_receipt is not None:
            key = stored_receipt.get("client_message_id") or stored_run.get("client_message_id")
            if not key:
                raise ValueError("a receipt requires a client_message_id")
        stored_opportunity.updated_at = datetime.now()

        self._opportunities[stored_opportunity.id] = stored_opportunity
        if memory is not None:
            self._memory[stored_opportunity.id] = copy.deepcopy(memory)
        if stored_case is not None:
            self._cases[stored_case.id] = stored_case
        self._runs.append(stored_run)
        if stored_receipt is not None:
            self._receipts[(stored_opportunity.id, key)] = stored_receipt

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

    def conversation_totals(self, opportunity_id: str) -> dict:
        """Token and cost totals across every run of one conversation."""
        runs = [r for r in self._runs if r.get("opportunity_id") == opportunity_id]
        total_tokens = sum(
            (r.get("totals") or {}).get("total_tokens", r.get("total_tokens", 0))
            for r in runs
        )
        cost_amount = sum(
            ((r.get("totals") or {}).get("cost") or {}).get(
                "amount", r.get("cost_amount", 0.0)
            )
            for r in runs
        )
        pricing_known = all(
            run.get("pricing_known", all(
                call.get("cost") is not None for call in run.get("llm_calls", [])
            ))
            for run in runs
        ) if runs else True

        return {
            "opportunity_id": opportunity_id,
            "run_count": len(runs),
            "total_tokens": total_tokens,
            "cost": {
                "amount": round(cost_amount, 8),
                "currency": "USD",
                "pricing_known": pricing_known,
            },
        }
