# -*- coding: utf-8 -*-
"""SQLite repository: standard library only, one file, survives restarts.

Every record is a JSON payload beside the few columns worth filtering on.
Writes are serialised with one lock; `check_same_thread=False` lets the HTTP
layer (P6) share the connection across worker threads.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Union

from .. import config
from ..domain.case import HumanCase
from ..domain.opportunity import Opportunity
from . import codec, migrations
from .base import Repository

_RECEIPT_SCHEMA_VERSION = 1


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


class SqliteRepository(Repository):
    def __init__(self, path: Union[str, Path, None] = None) -> None:
        target = ":memory:" if path == ":memory:" else Path(path or config.DEFAULT_DB_PATH)
        if target != ":memory:":
            target.parent.mkdir(parents=True, exist_ok=True)
        self.path = target
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(target), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        migrations.apply(self._conn)

    # ---- Opportunities ------------------------------------------------------

    def upsert_opportunity(self, opp: Opportunity) -> None:
        opp.updated_at = datetime.now()
        if not opp.created_at:
            opp.created_at = opp.updated_at
        with self._lock:
            with self._conn:
                self._write_opportunity(opp)
                self._sync_messages(opp)

    def _write_opportunity(self, opp: Opportunity) -> None:
        payload = codec.opportunity_to_dict(opp)
        self._conn.execute(
            """
            INSERT INTO opportunities
                (id, customer_name, state, product, priority, qualification,
                 human_takeover, created_at, updated_at, payload)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                customer_name=excluded.customer_name, state=excluded.state,
                product=excluded.product, priority=excluded.priority,
                qualification=excluded.qualification,
                human_takeover=excluded.human_takeover,
                updated_at=excluded.updated_at, payload=excluded.payload
            """,
            (
                opp.id, opp.customer_name, opp.state.value, opp.product.value,
                opp.priority.value if opp.priority else None, opp.qualification.value,
                int(opp.human_takeover), opp.created_at.isoformat(),
                opp.updated_at.isoformat(), _dumps(payload),
            ),
        )

    def get_opportunity(
        self, opportunity_id: str, *, history_limit: Optional[int] = None
    ) -> Optional[Opportunity]:
        row = self._conn.execute(
            "SELECT payload FROM opportunities WHERE id = ?", (opportunity_id,)
        ).fetchone()
        if not row:
            return None

        opp = codec.opportunity_from_dict(json.loads(row["payload"]))
        if history_limit is not None:
            # Trim history if requested
            if history_limit <= 0:
                opp.score_history = []
                opp.state_history = []
            else:
                opp.score_history = opp.score_history[-history_limit:] if opp.score_history else []
                opp.state_history = opp.state_history[-history_limit:] if opp.state_history else []
        return opp

    def list_opportunities(self) -> list[Opportunity]:
        rows = self._conn.execute("SELECT payload FROM opportunities ORDER BY updated_at ASC").fetchall()
        return [codec.opportunity_from_dict(json.loads(row["payload"])) for row in rows]

    def get_memory(self, opportunity_id: str) -> Optional[dict[str, Any]]:
        row = self._conn.execute(
            "SELECT payload FROM conversation_memory WHERE opportunity_id = ?",
            (opportunity_id,),
        ).fetchone()
        return json.loads(row["payload"]) if row else None

    def search_messages(
        self, opportunity_id: str, query: str, *, limit: int = 3
    ) -> list[dict[str, Any]]:
        needle = " ".join(str(query).split())[:120]
        if not needle:
            return []
        bounded_limit = max(1, min(int(limit), 5))
        escaped = needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM messages WHERE opportunity_id = ? LIMIT 1",
                (opportunity_id,),
            ).fetchone()
            if row is None:
                # Version 1 databases kept the source transcript only in the
                # opportunity payload. Hydrate the index lazily without changing it.
                stored = self._conn.execute(
                    "SELECT payload FROM opportunities WHERE id = ?", (opportunity_id,)
                ).fetchone()
                if stored is None:
                    return []
                opportunity = codec.opportunity_from_dict(json.loads(stored["payload"]))
                with self._conn:
                    self._sync_messages(opportunity)
            rows = self._conn.execute(
                """
                SELECT id, ts, role, text FROM messages
                WHERE opportunity_id = ? AND text LIKE ? ESCAPE '\\'
                ORDER BY seq DESC LIMIT ?
                """,
                (opportunity_id, f"%{escaped}%", bounded_limit),
            ).fetchall()
        return [
            {"message_id": row["id"], "timestamp": row["ts"], "role": row["role"], "text": row["text"]}
            for row in rows
        ]

    def _sync_messages(self, opportunity: Opportunity) -> None:
        """Maintain the scoped search index while preserving the JSON source of truth."""
        existing = {
            row["id"]: row["seq"]
            for row in self._conn.execute(
                "SELECT id, seq FROM messages WHERE opportunity_id = ?",
                (opportunity.id,),
            ).fetchall()
        }
        current_ids = set()
        for seq, message in enumerate(opportunity.messages):
            current_ids.add(message.id)
            self._conn.execute(
                """
                INSERT INTO messages
                    (opportunity_id, seq, id, ts, role, author, generation,
                     rep_name, text, client_message_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(opportunity_id, seq) DO UPDATE SET
                    id=excluded.id, ts=excluded.ts, role=excluded.role,
                    author=excluded.author, generation=excluded.generation,
                    rep_name=excluded.rep_name, text=excluded.text,
                    client_message_id=excluded.client_message_id
                """,
                (
                    opportunity.id, seq, message.id, message.ts.isoformat(),
                    message.role.value, message.author_value,
                    message.generation_value, message.rep_name, message.text,
                    message.client_message_id,
                ),
            )
        stale_ids = set(existing) - current_ids
        if stale_ids:
            self._conn.executemany(
                "DELETE FROM messages WHERE opportunity_id = ? AND id = ?",
                [(opportunity.id, message_id) for message_id in stale_ids],
            )

    def delete_opportunity(self, opportunity_id: str) -> bool:
        # `cases` and `message_receipts` carry opportunity_id but no
        # `ON DELETE CASCADE` (unlike messages/conversation_memory/score_history/
        # state_history), so without this they outlive the opportunity: a
        # stale case still shows "Taken Over" for a conversation that no
        # longer exists, and a stale receipt makes the *next* customer
        # message reusing the same client_message_id (a fresh conversation
        # started with the same customer id) try to replay a reply from an
        # opportunity that is no longer there.
        with self._lock:
            with self._conn:
                self._conn.execute("DELETE FROM cases WHERE opportunity_id = ?", (opportunity_id,))
                self._conn.execute(
                    "DELETE FROM message_receipts WHERE opportunity_id = ?", (opportunity_id,)
                )
                cursor = self._conn.execute(
                    "DELETE FROM opportunities WHERE id = ?", (opportunity_id,)
                )
        return cursor.rowcount > 0

    # ---- Cases ----------------------------------------------------------------

    def add_case(self, case: HumanCase) -> None:
        with self._lock:
            with self._conn:
                self._write_case(case)

    def update_case(self, case: HumanCase) -> None:
        with self._lock:
            with self._conn:
                self._write_case(case)

    def _write_case(self, case: HumanCase) -> None:
        payload = codec.case_to_dict(case)
        self._conn.execute(
            """
            INSERT INTO cases (id, opportunity_id, customer_name, state, product,
                               reason, summary, recommended_action, status, created_at, payload)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                opportunity_id=excluded.opportunity_id, customer_name=excluded.customer_name,
                state=excluded.state, product=excluded.product, reason=excluded.reason,
                summary=excluded.summary, recommended_action=excluded.recommended_action,
                status=excluded.status, created_at=excluded.created_at, payload=excluded.payload
            """,
            (
                case.id, case.opportunity_id, case.customer_name, case.state.value,
                case.product.value, case.reason, case.summary, case.recommended_action,
                case.status.value, case.created_at.isoformat(), _dumps(payload),
            ),
        )

    def get_case(self, case_id: str) -> Optional[HumanCase]:
        row = self._conn.execute("SELECT payload FROM cases WHERE id = ?", (case_id,)).fetchone()
        return codec.case_from_dict(json.loads(row["payload"])) if row else None

    def list_cases(self) -> list[HumanCase]:
        rows = self._conn.execute("SELECT payload FROM cases ORDER BY created_at ASC").fetchall()
        return [codec.case_from_dict(json.loads(row["payload"])) for row in rows]

    # ---- Idempotency receipts ----------------------------------------------

    def get_receipt(self, opportunity_id: str, client_message_id: str) -> Optional[dict[str, Any]]:
        row = self._conn.execute(
            "SELECT document FROM message_receipts WHERE opportunity_id = ? AND client_message_id = ?",
            (opportunity_id, client_message_id),
        ).fetchone()
        return json.loads(row["document"]) if row else None

    def save_receipt(self, opportunity_id: str, client_message_id: str, document: dict[str, Any]) -> None:
        with self._lock:
            with self._conn:
                self._write_receipt(opportunity_id, client_message_id, document)

    def _write_receipt(self, opportunity_id: str, client_message_id: str, document: dict[str, Any]) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO message_receipts
                (opportunity_id, client_message_id, schema_version, response, document, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                opportunity_id, client_message_id, _RECEIPT_SCHEMA_VERSION,
                _dumps(document), _dumps(document), datetime.now().isoformat(),
            ),
        )

    # ---- Agent runs -----------------------------------------------------------

    def save_run(self, run: dict[str, Any]) -> None:
        with self._lock:
            with self._conn:
                self._write_run(run)

    def _write_run(self, run: dict[str, Any]) -> None:
        totals = run.get("totals") or {}
        cost = totals.get("cost") or {}
        llm_calls = run.get("llm_calls") or []
        pricing_known = all(call.get("cost") is not None for call in llm_calls)
        self._conn.execute(
            """
            INSERT OR REPLACE INTO agent_runs
                (run_id, opportunity_id, client_message_id, status, started_at,
                 duration_ms, total_tokens, cost_amount, cost_currency, pricing_known, payload)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run["run_id"], run["opportunity_id"], run.get("client_message_id"),
                run["status"], run["started_at"], int(run.get("duration_ms", 0)),
                int(totals.get("total_tokens", 0)), float(cost.get("amount", 0.0)),
                cost.get("currency", "USD"), int(pricing_known), _dumps(run),
            ),
        )

    def save_turn(
        self,
        opportunity: Opportunity,
        run: dict[str, Any],
        *,
        case: Optional[HumanCase] = None,
        receipt: Optional[dict[str, Any]] = None,
        memory: Optional[dict[str, Any]] = None,
    ) -> None:
        """Commit every durable record from one turn in a single SQLite transaction."""
        key = None
        if receipt is not None:
            key = receipt.get("client_message_id") or run.get("client_message_id")
            if not key:
                raise ValueError("a receipt requires a client_message_id")
        opportunity.updated_at = datetime.now()
        if not opportunity.created_at:
            opportunity.created_at = opportunity.updated_at

        with self._lock:
            with self._conn:
                self._write_opportunity(opportunity)
                self._sync_messages(opportunity)
                if case is not None:
                    self._write_case(case)
                self._write_run(run)
                if memory is not None:
                    self._write_memory(opportunity.id, memory)
                if receipt is not None:
                    self._write_receipt(opportunity.id, key, receipt)

    def _write_memory(self, opportunity_id: str, memory: dict[str, Any]) -> None:
        updated_at = memory.get("updated_at") or datetime.now().isoformat()
        self._conn.execute(
            """
            INSERT INTO conversation_memory (opportunity_id, version, payload, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(opportunity_id) DO UPDATE SET
                version=excluded.version, payload=excluded.payload,
                updated_at=excluded.updated_at
            """,
            (opportunity_id, int(memory.get("version", 1)), _dumps(memory), updated_at),
        )

    def get_run(self, run_id: str) -> Optional[dict[str, Any]]:
        row = self._conn.execute("SELECT payload FROM agent_runs WHERE run_id = ?", (run_id,)).fetchone()
        return json.loads(row["payload"]) if row else None

    def list_runs(
        self,
        *,
        opportunity_id: Optional[str] = None,
        client_message_id: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        clauses, params = [], []
        if opportunity_id is not None:
            clauses.append("opportunity_id = ?")
            params.append(opportunity_id)
        if client_message_id is not None:
            clauses.append("client_message_id = ?")
            params.append(client_message_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._conn.execute(
            f"SELECT payload FROM agent_runs {where} ORDER BY started_at DESC, rowid DESC LIMIT ?",
            (*params, limit),
        ).fetchall()
        return [json.loads(row["payload"]) for row in rows]

    def conversation_totals(self, opportunity_id: str) -> dict:
        """Token and cost totals across every run of one conversation."""
        with self._lock:
            row = self._conn.execute(
                """
                SELECT COUNT(*) AS run_count,
                       COALESCE(SUM(total_tokens), 0) AS total_tokens,
                       COALESCE(SUM(cost_amount), 0) AS cost_amount,
                       COALESCE(MIN(pricing_known), 1) AS pricing_known
                FROM agent_runs WHERE opportunity_id = ?
                """,
                (opportunity_id,),
            ).fetchone()
        return {
            "opportunity_id": opportunity_id,
            "run_count": row["run_count"],
            "total_tokens": row["total_tokens"],
            "cost": {
                "amount": round(row["cost_amount"], 8),
                "currency": "USD",
                "pricing_known": bool(row["pricing_known"]),
            },
        }

    # ---- Lifecycle ----------------------------------------------------------------

    def close(self) -> None:
        with self._lock:
            self._conn.close()
