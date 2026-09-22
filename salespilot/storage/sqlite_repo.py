# -*- coding: utf-8 -*-
"""SQLite-backed repository (stdlib sqlite3, no third-party dependency).

Persists opportunities, their messages/score history/state history and HITL
cases so the agent state survives across processes and API server restarts.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from .. import config
from ..models import (
    CaseStatus,
    HumanCase,
    Intent,
    Message,
    Opportunity,
    OpportunityState,
    Product,
    ScoreCard,
    ScoreHistoryEntry,
    Signal,
    StateHistoryEntry,
)
from .base import BaseRepository

_SCHEMA = """
CREATE TABLE IF NOT EXISTS opportunities (
    id               TEXT PRIMARY KEY,
    customer_name    TEXT NOT NULL,
    state            TEXT NOT NULL,
    product          TEXT NOT NULL,
    signals          TEXT NOT NULL,
    signal_history   TEXT NOT NULL DEFAULT '[]',
    main_concern     TEXT,
    competitive_risk INTEGER NOT NULL,
    churn_risk       INTEGER NOT NULL DEFAULT 0,
    compliance_risk  INTEGER NOT NULL DEFAULT 0,
    expansion        TEXT NOT NULL,
    last_intent      TEXT NOT NULL,
    best_intent      TEXT NOT NULL DEFAULT 'generic',
    turns            INTEGER NOT NULL,
    score            TEXT,
    score_history    TEXT NOT NULL,
    state_history    TEXT NOT NULL DEFAULT '[]',
    human_takeover   INTEGER NOT NULL,
    human_intervention_required INTEGER NOT NULL DEFAULT 0,
    messages         TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cases (
    id                 TEXT PRIMARY KEY,
    opportunity_id     TEXT NOT NULL,
    customer_name      TEXT NOT NULL,
    state              TEXT NOT NULL,
    product            TEXT NOT NULL,
    reason             TEXT NOT NULL,
    summary            TEXT NOT NULL,
    recommended_action TEXT NOT NULL,
    status             TEXT NOT NULL,
    created_at         TEXT NOT NULL
);

-- P0-5: idempotency receipts. Stores the serialised response of the request
-- that first used a client_message_id, so a replay after a network timeout can
-- be answered without re-running the pipeline. Persisted (rather than kept in
-- process memory) so deduplication survives an API server restart.
CREATE TABLE IF NOT EXISTS message_receipts (
    opportunity_id    TEXT NOT NULL,
    client_message_id TEXT NOT NULL,
    schema_version    INTEGER NOT NULL DEFAULT 1,
    response          TEXT NOT NULL,
    created_at        TEXT NOT NULL,
    PRIMARY KEY (opportunity_id, client_message_id)
);
"""

# Bump when the shape of the serialised /api/messages response changes, so a
# stale receipt can be recognised during diagnosis. Receipts are still replayed
# across versions on purpose: returning a slightly old shape is safer than
# re-running the pipeline and inflating `turns` again, which is the exact bug
# idempotency exists to prevent.
_RECEIPT_SCHEMA_VERSION = 1


class SqliteRepository(BaseRepository):
    def __init__(self, db_path: Optional[str | Path] = None) -> None:
        super().__init__()
        path = Path(db_path) if db_path else config.DEFAULT_DB_PATH
        if str(path) != ":memory:":
            path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)

        existing_columns = {
            row["name"]
            for row in self._conn.execute("PRAGMA table_info(opportunities)")
        }
        if "signal_history" not in existing_columns:
            self._conn.execute(
                "ALTER TABLE opportunities ADD COLUMN signal_history TEXT NOT NULL DEFAULT '[]'"
            )
        if "best_intent" not in existing_columns:
            self._conn.execute(
                "ALTER TABLE opportunities ADD COLUMN best_intent TEXT NOT NULL DEFAULT 'generic'"
            )
        self._conn.commit()

    # ---- Opportunities ---------------------------------------------------

    def upsert_opportunity(self, opp: Opportunity) -> None:
        opp.updated_at = datetime.now()
        with self._lock:
            self._upsert_opportunity_locked(opp)

    def _upsert_opportunity_locked(self, opp: Opportunity) -> None:
        self._conn.execute(
            """
            INSERT INTO opportunities (
                id, customer_name, state, product, signals, signal_history, main_concern,
                competitive_risk, churn_risk, compliance_risk, expansion,
                last_intent, best_intent, turns, score, score_history, state_history,
                human_takeover, human_intervention_required,
                messages, created_at, updated_at
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?,
                ?, ?,
                ?, ?, ?
            )
            ON CONFLICT(id) DO UPDATE SET
                customer_name=excluded.customer_name,
                state=excluded.state,
                product=excluded.product,
                signals=excluded.signals,
                signal_history=excluded.signal_history,
                main_concern=excluded.main_concern,
                competitive_risk=excluded.competitive_risk,
                churn_risk=excluded.churn_risk,
                compliance_risk=excluded.compliance_risk,
                expansion=excluded.expansion,
                last_intent=excluded.last_intent,
                best_intent=excluded.best_intent,
                turns=excluded.turns,
                score=excluded.score,
                score_history=excluded.score_history,
                state_history=excluded.state_history,
                human_takeover=excluded.human_takeover,
                human_intervention_required=excluded.human_intervention_required,
                messages=excluded.messages,
                updated_at=excluded.updated_at
            """,
            (
                opp.id,
                opp.customer_name,
                opp.state.value,
                opp.product.value,
                json.dumps([s.value for s in opp.signals]),
                json.dumps([s.value for s in opp.signal_history]),
                opp.main_concern,
                int(opp.competitive_risk),
                int(opp.churn_risk),
                int(opp.compliance_risk),
                json.dumps(opp.expansion),
                opp.last_intent.value,
                opp.best_intent.value,
                opp.turns,
                json.dumps(_score_to_dict(opp.score)) if opp.score else None,
                json.dumps([
                    {"ts": e.timestamp.isoformat(), "score": e.score,
                     "state": e.state, "trigger": e.trigger}
                    for e in opp.score_history
                ]),
                json.dumps([
                    {"ts": e.timestamp.isoformat(), "from": e.from_state,
                     "to": e.to_state, "reason": e.reason}
                    for e in opp.state_history
                ]),
                int(opp.human_takeover),
                int(opp.human_intervention_required),
                json.dumps([
                    {
                        "role": m.role,
                        "text": m.text,
                        "ts": m.ts.isoformat(),
                        "client_message_id": m.client_message_id,
                    }
                    for m in opp.messages
                ]),
                opp.created_at.isoformat(),
                opp.updated_at.isoformat(),
            ),
        )
        self._conn.commit()

    def get_opportunity(self, opp_id: str) -> Optional[Opportunity]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM opportunities WHERE id = ?", (opp_id,)
            ).fetchone()
        return _row_to_opportunity(row) if row else None

    def list_opportunities(self) -> list[Opportunity]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM opportunities ORDER BY updated_at ASC"
            ).fetchall()
        return [_row_to_opportunity(row) for row in rows]

    def delete_opportunity(self, opp_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM opportunities WHERE id = ?", (opp_id,))
            self._conn.commit()

    # ---- HITL cases ------------------------------------------------------

    def add_case(self, case: HumanCase) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO cases (
                    id, opportunity_id, customer_name, state, product, reason,
                    summary, recommended_action, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                ),
            )
            self._conn.commit()

    def list_cases(self) -> list[HumanCase]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM cases ORDER BY created_at ASC"
            ).fetchall()
        return [_row_to_case(row) for row in rows]

    # ---- Idempotency receipts (P0-5) ------------------------------------

    def get_message_receipt(
        self, opportunity_id: str, client_message_id: str
    ) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT response FROM message_receipts "
                "WHERE opportunity_id = ? AND client_message_id = ?",
                (opportunity_id, client_message_id),
            ).fetchone()
        return json.loads(row["response"]) if row else None

    def save_message_receipt(
        self, opportunity_id: str, client_message_id: str, response: dict
    ) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO message_receipts (
                    opportunity_id, client_message_id, schema_version,
                    response, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    opportunity_id,
                    client_message_id,
                    _RECEIPT_SCHEMA_VERSION,
                    json.dumps(response, ensure_ascii=False),
                    datetime.now().isoformat(),
                ),
            )
            self._conn.commit()

    # ---- Lifecycle -------------------------------------------------------

    def close(self) -> None:
        self._conn.close()


# ---- (de)serialisation helpers -------------------------------------------


def _score_to_dict(score: ScoreCard) -> dict:
    return {
        "purchase_intent": score.purchase_intent,
        "purchase_readiness": score.purchase_readiness,
        "product_potential": score.product_potential,
        "expansion": score.expansion,
        "engagement": score.engagement,
        "total": score.total,
        "priority": score.priority.value,
    }


def _row_to_opportunity(row: sqlite3.Row) -> Opportunity:
    from ..models import Priority

    score_data = json.loads(row["score"]) if row["score"] else None
    score = None
    if score_data:
        score = ScoreCard(
            purchase_intent=score_data["purchase_intent"],
            purchase_readiness=score_data["purchase_readiness"],
            product_potential=score_data["product_potential"],
            expansion=score_data["expansion"],
            engagement=score_data["engagement"],
            total=score_data["total"],
            priority=Priority(score_data["priority"]),
        )

    messages = [
        Message(
            role=m["role"],
            text=m["text"],
            ts=datetime.fromisoformat(m["ts"]),
            # Rows written before P0-5 have no key; default to None rather than
            # failing to load an existing database.
            client_message_id=m.get("client_message_id"),
        )
        for m in json.loads(row["messages"])
    ]

    raw_sh = json.loads(row["score_history"])
    score_history = [
        ScoreHistoryEntry(
            timestamp=datetime.fromisoformat(e["ts"]),
            score=e["score"],
            state=e["state"],
            trigger=e["trigger"],
        )
        for e in raw_sh
    ]

    raw_sth = json.loads(row["state_history"]) if row["state_history"] else "[]"
    state_history = [
        StateHistoryEntry(
            timestamp=datetime.fromisoformat(e["ts"]),
            from_state=e["from"],
            to_state=e["to"],
            reason=e["reason"],
        )
        for e in raw_sth
    ]

    return Opportunity(
        id=row["id"],
        customer_name=row["customer_name"],
        state=OpportunityState(row["state"]),
        product=Product(row["product"]),
        signals=[Signal(s) for s in json.loads(row["signals"])],
        signal_history=[Signal(s) for s in json.loads(row["signal_history"])] if "signal_history" in row.keys() and row["signal_history"] else [],
        main_concern=row["main_concern"],
        competitive_risk=bool(row["competitive_risk"]),
        churn_risk=bool(row["churn_risk"]),
        compliance_risk=bool(row["compliance_risk"]),
        expansion=json.loads(row["expansion"]),
        last_intent=Intent(row["last_intent"]),
        best_intent=(
            Intent(row["best_intent"])
            if "best_intent" in row.keys() and row["best_intent"]
            else Intent(row["last_intent"])
        ),
        turns=row["turns"],
        score=score,
        score_history=score_history,
        state_history=state_history,
        human_takeover=bool(row["human_takeover"]),
        human_intervention_required=bool(row["human_intervention_required"]),
        messages=messages,
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def _row_to_case(row: sqlite3.Row) -> HumanCase:
    return HumanCase(
        id=row["id"],
        opportunity_id=row["opportunity_id"],
        customer_name=row["customer_name"],
        state=OpportunityState(row["state"]),
        product=Product(row["product"]),
        reason=row["reason"],
        summary=row["summary"],
        recommended_action=row["recommended_action"],
        status=CaseStatus(row["status"]),
        created_at=datetime.fromisoformat(row["created_at"]),
    )
