# -*- coding: utf-8 -*-
"""SQLite repository. Standard library only — no ORM, no migration framework.

Schema in `schema.sql`. Messages and the two histories are normalised into their own
tables, which is what makes an incremental `?since=` read and a bounded history read
cheap instead of requiring the whole conversation to be loaded first.

`PRAGMA foreign_keys = ON` is set on every connection, so deleting an opportunity
takes its messages with it. Without it a reset conversation would come back with its
old transcript attached — SQLite leaves foreign keys off by default, which is a
pitfall worth naming rather than discovering.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from .. import config
from ..domain.case import HumanCase
from ..domain.enums import (
    CaseStatus,
    Generation,
    Intent,
    MessageAuthor,
    MessageRole,
    OpportunityState,
    Priority,
    Product,
    Qualification,
    Signal,
)
from ..domain.message import Message
from ..domain.opportunity import (
    Opportunity,
    ScoreCard,
    ScoreHistoryEntry,
    StateHistoryEntry,
)
from .base import bound_history, resolve_cursor

_SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"

# Bumped when the shape of a stored receipt changes. Receipts are still replayed
# across versions on purpose: returning a slightly older response shape is safer than
# re-running the pipeline and inflating the message count again, which is the exact
# bug idempotency exists to prevent.
RECEIPT_SCHEMA_VERSION = 1


class SqliteRepository:
    def __init__(self, db_path: Optional[str | Path] = None) -> None:
        path = Path(db_path) if db_path else config.DEFAULT_DB_PATH
        if str(path) != ":memory:":
            path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))
        # Existing local demo databases predate the confirmation state.
        columns = {row[1] for row in self._conn.execute("PRAGMA table_info(opportunities)")}
        if "pending_handoff_reason" not in columns:
            self._conn.execute(
                "ALTER TABLE opportunities ADD COLUMN pending_handoff_reason TEXT"
            )
        if "pending_question_field" not in columns:
            self._conn.execute(
                "ALTER TABLE opportunities ADD COLUMN pending_question_field TEXT"
            )
        if "collected_answers" not in columns:
            self._conn.execute(
                "ALTER TABLE opportunities ADD COLUMN collected_answers TEXT NOT NULL DEFAULT '{}'"
            )
        if "evidence_sources" not in columns:
            self._conn.execute(
                "ALTER TABLE opportunities ADD COLUMN evidence_sources TEXT NOT NULL DEFAULT '{}'"
            )
        score_columns = {row[1] for row in self._conn.execute("PRAGMA table_info(score_history)")}
        if "evidence" not in score_columns:
            self._conn.execute(
                "ALTER TABLE score_history ADD COLUMN evidence TEXT NOT NULL DEFAULT '{}'"
            )
        self._conn.commit()

    # ---- Opportunities ---------------------------------------------------

    def upsert_opportunity(self, opp: Opportunity) -> None:
        opp.updated_at = datetime.now()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO opportunities (
                    id, customer_name, state, product, signals, signal_history,
                    main_concern, competitive_risk, churn_risk, compliance_risk,
                    expansion, last_intent, best_intent, urgency_observed,
                    customer_message_count, score, human_takeover,
                    human_intervention_required, pending_handoff_reason,
                    pending_question_field, collected_answers, evidence_sources, qualification,
                    qualification_reason, solicitation_count, created_at, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
                    urgency_observed=excluded.urgency_observed,
                    customer_message_count=excluded.customer_message_count,
                    score=excluded.score,
                    human_takeover=excluded.human_takeover,
                    human_intervention_required=excluded.human_intervention_required,
                    pending_handoff_reason=excluded.pending_handoff_reason,
                    pending_question_field=excluded.pending_question_field,
                    collected_answers=excluded.collected_answers,
                    evidence_sources=excluded.evidence_sources,
                    qualification=excluded.qualification,
                    qualification_reason=excluded.qualification_reason,
                    solicitation_count=excluded.solicitation_count,
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
                    int(opp.urgency_observed),
                    opp.customer_message_count,
                    json.dumps(_score_to_dict(opp.score)) if opp.score else None,
                    int(opp.human_takeover),
                    int(opp.human_intervention_required),
                    opp.pending_handoff_reason,
                    opp.pending_question_field,
                    json.dumps(opp.collected_answers),
                    json.dumps(opp.evidence_sources),
                    opp.qualification.value,
                    opp.qualification_reason,
                    opp.solicitation_count,
                    opp.created_at.isoformat(),
                    opp.updated_at.isoformat(),
                ),
            )
            # Rewritten wholesale rather than diffed. The transcript is append-only in
            # practice, but a rewrite cannot leave a stale row behind, and these are
            # tens of rows, not thousands.
            self._replace_children(opp)
            self._conn.commit()

    def _replace_children(self, opp: Opportunity) -> None:
        self._conn.execute("DELETE FROM messages WHERE opportunity_id = ?", (opp.id,))
        self._conn.executemany(
            """
            INSERT INTO messages (
                opportunity_id, seq, id, ts, role, author, generation, rep_name,
                text, client_message_id
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            [
                (
                    opp.id, seq, message.id, message.ts.isoformat(),
                    message.role.value, message.author_value,
                    message.generation_value, message.rep_name, message.text,
                    message.client_message_id,
                )
                for seq, message in enumerate(opp.messages)
            ],
        )

        self._conn.execute(
            "DELETE FROM score_history WHERE opportunity_id = ?", (opp.id,)
        )
        self._conn.executemany(
            """
            INSERT INTO score_history (opportunity_id, seq, ts, score, state, trigger, evidence)
            VALUES (?,?,?,?,?,?,?)
            """,
            [
                (opp.id, seq, entry.timestamp.isoformat(), entry.score,
                 entry.state, entry.trigger, json.dumps(entry.evidence))
                for seq, entry in enumerate(opp.score_history)
            ],
        )

        self._conn.execute(
            "DELETE FROM state_history WHERE opportunity_id = ?", (opp.id,)
        )
        self._conn.executemany(
            """
            INSERT INTO state_history (
                opportunity_id, seq, ts, from_state, to_state, reason
            ) VALUES (?,?,?,?,?,?)
            """,
            [
                (opp.id, seq, entry.timestamp.isoformat(), entry.from_state,
                 entry.to_state, entry.reason)
                for seq, entry in enumerate(opp.state_history)
            ],
        )

    def get_opportunity(
        self, opp_id: str, *, history_limit: Optional[int] = None
    ) -> Optional[Opportunity]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM opportunities WHERE id = ?", (opp_id,)
            ).fetchone()
            if row is None:
                return None
            messages = self._load_messages(opp_id)
            scores = self._load_score_history(opp_id, history_limit)
            states = self._load_state_history(opp_id, history_limit)
        return _row_to_opportunity(row, messages, scores, states)

    def list_opportunities(self) -> list[Opportunity]:
        with self._lock:
            ids = [
                row["id"]
                for row in self._conn.execute(
                    "SELECT id FROM opportunities ORDER BY updated_at ASC"
                )
            ]
        return [
            opp for opp in (self.get_opportunity(opp_id) for opp_id in ids)
            if opp is not None
        ]

    def delete_opportunity(self, opp_id: str) -> None:
        with self._lock:
            # Explicit child deletes as well as the cascade: the cascade depends on the
            # pragma being on, and a silently orphaned transcript would reappear under
            # a reused id.
            for table in ("messages", "score_history", "state_history"):
                self._conn.execute(
                    f"DELETE FROM {table} WHERE opportunity_id = ?", (opp_id,)
                )
            self._conn.execute("DELETE FROM opportunities WHERE id = ?", (opp_id,))
            self._conn.commit()

    def messages_since(
        self, opp_id: str, *, cursor: Optional[str] = None
    ) -> list[Message]:
        with self._lock:
            messages = self._load_messages(opp_id)
        after = resolve_cursor(cursor, messages)
        return messages[after + 1:]

    # ---- Human cases -----------------------------------------------------

    def add_case(self, case: HumanCase) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO cases (
                    id, opportunity_id, customer_name, state, product, reason,
                    summary, recommended_action, status, created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    case.id, case.opportunity_id, case.customer_name,
                    case.state.value, case.product.value, case.reason,
                    case.summary, case.recommended_action, case.status.value,
                    case.created_at.isoformat(),
                ),
            )
            self._conn.commit()

    # One active case per opportunity, so an update is the same write as an insert.
    update_case = add_case

    def get_case(self, case_id: str) -> Optional[HumanCase]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM cases WHERE id = ?", (case_id,)
            ).fetchone()
        return _row_to_case(row) if row else None

    def list_cases(self) -> list[HumanCase]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM cases ORDER BY created_at ASC"
            ).fetchall()
        return [_row_to_case(row) for row in rows]

    def active_case_for(self, opp_id: str) -> Optional[HumanCase]:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT * FROM cases
                WHERE opportunity_id = ? AND status != ?
                ORDER BY created_at ASC LIMIT 1
                """,
                (opp_id, CaseStatus.CLOSED.value),
            ).fetchone()
        return _row_to_case(row) if row else None

    # ---- Idempotency receipts -------------------------------------------

    def get_message_receipt(
        self, opp_id: str, client_message_id: str
    ) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT response FROM message_receipts "
                "WHERE opportunity_id = ? AND client_message_id = ?",
                (opp_id, client_message_id),
            ).fetchone()
        return json.loads(row["response"]) if row else None

    def save_message_receipt(
        self, opp_id: str, client_message_id: str, response: dict
    ) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO message_receipts (
                    opportunity_id, client_message_id, schema_version, response,
                    created_at
                ) VALUES (?,?,?,?,?)
                """,
                (
                    opp_id, client_message_id, RECEIPT_SCHEMA_VERSION,
                    json.dumps(response, ensure_ascii=False),
                    datetime.now().isoformat(),
                ),
            )
            self._conn.commit()

    # ---- Agent runs ------------------------------------------------------

    def save_agent_run(self, run: Any) -> None:
        payload = run.to_dict() if hasattr(run, "to_dict") else dict(run)
        totals = payload.get("totals", {})
        cost = totals.get("cost", {})
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO agent_runs (
                    run_id, opportunity_id, client_message_id, status, started_at,
                    duration_ms, total_tokens, cost_amount, cost_currency,
                    pricing_known, payload
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    payload["run_id"],
                    payload["opportunity_id"],
                    payload.get("client_message_id"),
                    payload.get("status", "ok"),
                    payload.get("started_at"),
                    payload.get("duration_ms", 0),
                    totals.get("total_tokens", 0),
                    cost.get("amount", 0.0),
                    cost.get("currency", "USD"),
                    int(cost.get("pricing_known", True)),
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
            self._conn.commit()

    def get_agent_run(self, run_id: str) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT payload FROM agent_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        return json.loads(row["payload"]) if row else None

    def list_agent_runs(
        self,
        opp_id: str,
        *,
        client_message_id: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[dict]:
        sql = "SELECT payload FROM agent_runs WHERE opportunity_id = ?"
        params: list[Any] = [opp_id]
        if client_message_id is not None:
            sql += " AND client_message_id = ?"
            params.append(client_message_id)
        # `rowid` breaks the tie when two runs share a start timestamp, so "newest
        # first" is a total order rather than an arbitrary one.
        sql += " ORDER BY started_at DESC, rowid DESC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [json.loads(row["payload"]) for row in rows]

    def conversation_totals(self, opp_id: str) -> dict:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT COUNT(*) AS run_count,
                       COALESCE(SUM(total_tokens), 0) AS total_tokens,
                       COALESCE(SUM(cost_amount), 0) AS cost_amount,
                       COALESCE(MIN(pricing_known), 1) AS pricing_known
                FROM agent_runs WHERE opportunity_id = ?
                """,
                (opp_id,),
            ).fetchone()
        return {
            "opportunity_id": opp_id,
            "run_count": row["run_count"],
            "total_tokens": row["total_tokens"],
            "cost": {
                "amount": round(row["cost_amount"], 8),
                "currency": "USD",
                # MIN over a boolean column: one unpriced run makes the total
                # unpriced, because a sum is only as trustworthy as its worst part.
                "pricing_known": bool(row["pricing_known"]),
            },
        }

    # ---- Lifecycle -------------------------------------------------------

    def close(self) -> None:
        self._conn.close()

    # ---- Child loads -----------------------------------------------------

    def _load_messages(self, opp_id: str) -> list[Message]:
        rows = self._conn.execute(
            "SELECT * FROM messages WHERE opportunity_id = ? ORDER BY seq ASC",
            (opp_id,),
        ).fetchall()
        return [
            Message(
                role=MessageRole(row["role"]),
                text=row["text"],
                id=row["id"],
                ts=datetime.fromisoformat(row["ts"]),
                author=MessageAuthor(row["author"]) if row["author"] else None,
                generation=Generation(row["generation"]) if row["generation"] else None,
                rep_name=row["rep_name"],
                client_message_id=row["client_message_id"],
            )
            for row in rows
        ]

    def _load_score_history(
        self, opp_id: str, limit: Optional[int]
    ) -> list[ScoreHistoryEntry]:
        rows = self._conn.execute(
            "SELECT * FROM score_history WHERE opportunity_id = ? ORDER BY seq ASC",
            (opp_id,),
        ).fetchall()
        entries = [
            ScoreHistoryEntry(
                timestamp=datetime.fromisoformat(row["ts"]),
                score=row["score"], state=row["state"], trigger=row["trigger"],
                evidence=json.loads(row["evidence"]),
            )
            for row in rows
        ]
        return bound_history(entries, limit)

    def _load_state_history(
        self, opp_id: str, limit: Optional[int]
    ) -> list[StateHistoryEntry]:
        rows = self._conn.execute(
            "SELECT * FROM state_history WHERE opportunity_id = ? ORDER BY seq ASC",
            (opp_id,),
        ).fetchall()
        entries = [
            StateHistoryEntry(
                timestamp=datetime.fromisoformat(row["ts"]),
                from_state=row["from_state"], to_state=row["to_state"],
                reason=row["reason"],
            )
            for row in rows
        ]
        return bound_history(entries, limit)


# ---- (de)serialisation ----------------------------------------------------


def _score_to_dict(score: ScoreCard) -> dict:
    return {
        "need_identified": score.need_identified,
        "product_potential": score.product_potential,
        "expansion": score.expansion,
        "fit_total": score.fit_total,
        "purchase_intent": score.purchase_intent,
        "purchase_readiness": score.purchase_readiness,
        "engagement": score.engagement,
        "engagement_depth": score.engagement_depth,
        "engagement_urgency": score.engagement_urgency,
        "engagement_recency": score.engagement_recency,
        "behaviour_raw": score.behaviour_raw,
        "behaviour_total": score.behaviour_total,
        "total": score.total,
        "priority": score.priority.value,
    }


def _dict_to_score(data: dict) -> ScoreCard:
    return ScoreCard(
        need_identified=data.get("need_identified", 0),
        product_potential=data.get("product_potential", 0),
        expansion=data.get("expansion", 0),
        fit_total=data.get("fit_total", 0),
        purchase_intent=data.get("purchase_intent", 0),
        purchase_readiness=data.get("purchase_readiness", 0),
        engagement=data.get("engagement", 0),
        engagement_depth=data.get("engagement_depth", 0),
        engagement_urgency=data.get("engagement_urgency", 0),
        engagement_recency=data.get("engagement_recency", 100),
        behaviour_raw=data.get("behaviour_raw", 0),
        behaviour_total=data.get("behaviour_total", 0),
        total=data.get("total", 0),
        priority=Priority(data.get("priority", Priority.LOW.value)),
    )


def _row_to_opportunity(row, messages, score_history, state_history) -> Opportunity:
    opp = Opportunity(
        id=row["id"],
        customer_name=row["customer_name"],
        state=OpportunityState(row["state"]),
        product=Product(row["product"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )
    opp.signals = [Signal(value) for value in json.loads(row["signals"])]
    opp.signal_history = [Signal(v) for v in json.loads(row["signal_history"])]
    opp.main_concern = row["main_concern"]
    opp.competitive_risk = bool(row["competitive_risk"])
    opp.churn_risk = bool(row["churn_risk"])
    opp.compliance_risk = bool(row["compliance_risk"])
    opp.expansion = json.loads(row["expansion"])
    opp.last_intent = Intent(row["last_intent"])
    opp.best_intent = Intent(row["best_intent"])
    opp.urgency_observed = bool(row["urgency_observed"])
    opp.customer_message_count = row["customer_message_count"]
    opp.score = _dict_to_score(json.loads(row["score"])) if row["score"] else None
    opp.human_takeover = bool(row["human_takeover"])
    opp.human_intervention_required = bool(row["human_intervention_required"])
    opp.pending_handoff_reason = row["pending_handoff_reason"]
    opp.pending_question_field = row["pending_question_field"]
    opp.collected_answers = json.loads(row["collected_answers"])
    opp.evidence_sources = json.loads(row["evidence_sources"])
    opp.qualification = Qualification(row["qualification"])
    opp.qualification_reason = row["qualification_reason"]
    opp.solicitation_count = row["solicitation_count"]
    opp.messages = messages
    opp.score_history = score_history
    opp.state_history = state_history
    return opp


def _row_to_case(row) -> HumanCase:
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
