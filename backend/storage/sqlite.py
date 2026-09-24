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
        migrations.apply(self._conn)

    # ---- Opportunities ------------------------------------------------------

    def upsert_opportunity(self, opp: Opportunity) -> None:
        opp.updated_at = datetime.now()
        if not opp.created_at:
            opp.created_at = opp.updated_at
        payload = codec.opportunity_to_dict(opp)
        with self._lock:
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
                    opp.id,
                    opp.customer_name,
                    opp.state.value,
                    opp.product.value,
                    opp.priority.value if opp.priority else None,
                    opp.qualification.value,
                    int(opp.human_takeover),
                    opp.created_at.isoformat(),
                    opp.updated_at.isoformat(),
                    _dumps(payload),
                ),
            )
            self._conn.commit()

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
            opp.score_history = opp.score_history[-history_limit:] if opp.score_history else []
            opp.state_history = opp.state_history[-history_limit:] if opp.state_history else []
        return opp

    def list_opportunities(self) -> list[Opportunity]:
        rows = self._conn.execute("SELECT payload FROM opportunities ORDER BY updated_at ASC").fetchall()
        return [codec.opportunity_from_dict(json.loads(row["payload"])) for row in rows]

    def delete_opportunity(self, opportunity_id: str) -> bool:
        with self._lock:
            cursor = self._conn.execute("DELETE FROM opportunities WHERE id = ?", (opportunity_id,))
            self._conn.commit()
        return cursor.rowcount > 0

    # ---- Cases ----------------------------------------------------------------

    def add_case(self, case: HumanCase) -> None:
        self._write_case(case)

    def update_case(self, case: HumanCase) -> None:
        self._write_case(case)

    def _write_case(self, case: HumanCase) -> None:
        payload = codec.case_to_dict(case)
        with self._lock:
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
                    case.id,
                    case.opportunity_id,
                    case.customer_name,
                    case.state.value,
                    case.product.value,
                    case.reason,
                    case.summary,
                    case.recommended_action,
                    case.status.value,
                    case.created_at.isoformat(),
                    _dumps(payload),
                ),
            )
            self._conn.commit()

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
            self._conn.execute(
                """
                INSERT OR REPLACE INTO message_receipts
                    (opportunity_id, client_message_id, schema_version, response, document, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    opportunity_id,
                    client_message_id,
                    _RECEIPT_SCHEMA_VERSION,
                    _dumps(document),  # response = document for compatibility
                    _dumps(document),
                    datetime.now().isoformat(),
                ),
            )
            self._conn.commit()

    # ---- Agent runs -----------------------------------------------------------

    def save_run(self, run: dict[str, Any]) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO agent_runs
                    (run_id, opportunity_id, client_message_id, status, started_at, payload)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    run["run_id"],
                    run["opportunity_id"],
                    run.get("client_message_id"),
                    run["status"],
                    run["started_at"],
                    _dumps(run),
                ),
            )
            self._conn.commit()

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
