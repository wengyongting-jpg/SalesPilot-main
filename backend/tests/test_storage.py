# -*- coding: utf-8 -*-
"""P5: the repository contract, satisfied by both backends.

The same assertions run against `MemoryRepository` and `SqliteRepository`.
SQLite additionally proves the P5 acceptance criterion that a receipt — and
the agent runs — survive a simulated restart.
"""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from backend.domain.case import HumanCase
from backend.domain.enums import (
    CaseStatus,
    Intent,
    OpportunityState,
    Priority,
    Product,
    Qualification,
    Signal,
)
from backend.domain.message import Message
from backend.domain.opportunity import Opportunity, ScoreCard, ScoreHistoryEntry, StateHistoryEntry
from backend.storage import InMemoryRepository, SqliteRepository, codec


def _opportunity(opp_id: str = "C-1") -> Opportunity:
    return Opportunity(
        id=opp_id,
        customer_name="Sarah",
        state=OpportunityState.HIGH_INTENT,
        product=Product.PLUS,
        signals=[Signal.PURCHASE],
        signal_history=[Signal.PURCHASE, Signal.HESITATION],
        main_concern="Price",
        competitive_risk=True,
        expansion=["Family"],
        last_intent=Intent.APPLICATION,
        best_intent=Intent.APPLICATION,
        urgency_observed=True,
        customer_message_count=3,
        score=ScoreCard(fit_total=70, behaviour_total=80, total=75, priority=Priority.HIGH),
        score_history=[ScoreHistoryEntry(
            datetime(2026, 9, 22, 12, 0), 45, "Cold Lead", "message(rule)", evidence={"intent": "application"}
        )],
        state_history=[StateHistoryEntry(datetime(2026, 9, 22, 12, 0), "Cold Lead", "High Intent", "purchase")],
        human_takeover=True,
        pending_handoff_reason="needs a representative",
        pending_question_field="budget",
        collected_answers={"budget": "1000"},
        evidence_sources={"budget": "customer message"},
        qualification=Qualification.HELD,
        qualification_reason="Advertising",
        solicitation_count=2,
        messages=[
            Message.from_customer("hi", client_message_id="c-1"),
            Message.from_ai("hello", generation="template"),
            Message.from_human("rep here", rep_name="Ana"),
        ],
    )


def _run(run_id: str, opp_id: str, key: str, started: str) -> dict:
    return {
        "run_id": run_id,
        "opportunity_id": opp_id,
        "client_message_id": key,
        "status": "ok",
        "started_at": started,
        "steps": [],
        "llm_calls": [],
        "tool_calls": [],
        "totals": {"agent_step_count": 0, "llm_call_count": 0, "tool_call_count": 0, "total_tokens": 0},
    }


class RepositoryContract:
    """Mixed into a TestCase per backend; `self.repo` is provided by `setUp`."""

    def test_opportunity_round_trips_every_field(self):
        original = _opportunity()
        self.repo.upsert_opportunity(original)
        loaded = self.repo.get_opportunity("C-1")
        self.assertEqual(codec.opportunity_to_dict(loaded), codec.opportunity_to_dict(original))

    def test_older_opportunity_payload_defaults_new_persistence_fields(self):
        payload = codec.opportunity_to_dict(_opportunity())
        for key in (
            "pending_handoff_reason", "pending_question_field", "collected_answers",
            "evidence_sources",
        ):
            payload.pop(key)
        for entry in payload["score_history"]:
            entry.pop("evidence", None)

        restored = codec.opportunity_from_dict(payload)
        self.assertIsNone(restored.pending_handoff_reason)
        self.assertIsNone(restored.pending_question_field)
        self.assertEqual({}, restored.collected_answers)
        self.assertEqual({}, restored.evidence_sources)
        self.assertEqual({}, restored.score_history[0].evidence)

    def test_message_ids_and_timestamps_are_preserved_exactly(self):
        original = _opportunity()
        self.repo.upsert_opportunity(original)
        loaded = self.repo.get_opportunity("C-1")
        self.assertEqual([m.id for m in loaded.messages], [m.id for m in original.messages])
        self.assertEqual([m.ts for m in loaded.messages], [m.ts for m in original.messages])
        self.assertEqual(loaded.messages[2].rep_name, "Ana")
        self.assertEqual(loaded.messages[1].generation_value, "template")

    def test_zero_history_limit_returns_no_score_or_state_history(self):
        self.repo.upsert_opportunity(_opportunity())

        loaded = self.repo.get_opportunity("C-1", history_limit=0)

        self.assertEqual([], loaded.score_history)
        self.assertEqual([], loaded.state_history)
        stored = self.repo.get_opportunity("C-1")
        self.assertEqual(1, len(stored.score_history))
        self.assertEqual(1, len(stored.state_history))

    def test_history_search_is_scoped_and_bounded(self):
        first = _opportunity("C-1")
        first.messages.extend([
            Message.from_customer("The appointment is on Thursday.", id="old-1"),
            Message.from_ai("I have noted Thursday.", generation="template", id="old-2"),
        ])
        second = _opportunity("C-2")
        second.messages.append(Message.from_customer("Thursday is also fine.", id="other-1"))
        self.repo.upsert_opportunity(first)
        self.repo.upsert_opportunity(second)

        results = self.repo.search_messages("C-1", "Thursday", limit=99)
        self.assertEqual(["old-2", "old-1"], [item["message_id"] for item in results])
        self.assertLessEqual(len(results), 5)
        self.assertEqual([], self.repo.search_messages("C-2", "appointment"))
        self.assertEqual([], self.repo.search_messages("missing", "Thursday"))

    def test_memory_record_round_trips_and_deletes_with_opportunity(self):
        opportunity = _opportunity()
        memory = {
            "version": 1,
            "facts": [{"text": "Needs private hospital coverage", "source_message_ids": ["source-1"]}],
            "covered_message_ids": ["source-1"],
            "through_message_id": "source-1",
            "updated_at": "2026-09-25T10:00:00",
        }
        self.repo.save_turn(opportunity, _run("ar-memory", "C-1", "k-memory", "2026-09-25T10:00:00"), memory=memory)
        self.assertEqual(memory, self.repo.get_memory("C-1"))
        self.repo.delete_opportunity("C-1")
        self.assertIsNone(self.repo.get_memory("C-1"))

    def test_list_and_delete(self):
        self.repo.upsert_opportunity(_opportunity("C-1"))
        self.repo.upsert_opportunity(_opportunity("C-2"))
        self.assertEqual({o.id for o in self.repo.list_opportunities()}, {"C-1", "C-2"})
        self.assertTrue(self.repo.delete_opportunity("C-1"))
        self.assertFalse(self.repo.delete_opportunity("C-1"))
        self.assertIsNone(self.repo.get_opportunity("C-1"))

    def test_cases_and_the_one_active_case_rule(self):
        case = HumanCase(
            opportunity_id="C-1", customer_name="Sarah", state=OpportunityState.HIGH_INTENT,
            product=Product.PLUS, reason="r", summary="s", recommended_action="a",
        )
        self.repo.add_case(case)
        self.assertEqual(self.repo.get_case(case.id).reason, "r")
        self.assertEqual(self.repo.active_case_for("C-1").id, case.id)
        case.status = CaseStatus.CLOSED
        self.repo.update_case(case)
        self.assertIsNone(self.repo.active_case_for("C-1"))
        self.assertEqual(self.repo.get_case(case.id).status, CaseStatus.CLOSED)

    def test_receipts(self):
        self.assertIsNone(self.repo.get_receipt("C-1", "k"))
        self.repo.save_receipt("C-1", "k", {"reply": "hi", "facts": ["a"]})
        self.assertEqual(self.repo.get_receipt("C-1", "k"), {"reply": "hi", "facts": ["a"]})
        self.assertIsNone(self.repo.get_receipt("C-2", "k"))

    def test_runs_are_queryable_by_opportunity_and_by_client_message_id(self):
        for i in range(3):
            self.repo.save_run(_run(f"ar-{i}", "C-1", f"k-{i}", f"2026-09-22T10:00:0{i}"))
        self.repo.save_run(_run("ar-x", "C-2", "k-x", "2026-09-22T10:00:09"))

        by_opp = self.repo.list_runs(opportunity_id="C-1")
        self.assertEqual([r["run_id"] for r in by_opp], ["ar-2", "ar-1", "ar-0"])
        self.assertEqual(self.repo.list_runs(client_message_id="k-1")[0]["run_id"], "ar-1")
        self.assertEqual(len(self.repo.list_runs(limit=2)), 2)
        self.assertEqual(self.repo.get_run("ar-x")["opportunity_id"], "C-2")
        self.assertIsNone(self.repo.get_run("nope"))


class TestMemoryRepository(RepositoryContract, unittest.TestCase):
    def setUp(self):
        self.repo = InMemoryRepository()


class TestSqliteRepository(RepositoryContract, unittest.TestCase):
    def setUp(self):
        self.repo = SqliteRepository(":memory:")

    def tearDown(self):
        self.repo.close()


class TestSqliteSurvivesRestart(unittest.TestCase):
    """P5 acceptance: a receipt survives a simulated restart under SQLite."""

    def test_receipt_opportunity_case_and_runs_survive_reopen(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "restart.db"
            first = SqliteRepository(path)
            first.upsert_opportunity(_opportunity())
            first.add_case(HumanCase(
                opportunity_id="C-1", customer_name="Sarah", state=OpportunityState.HIGH_INTENT,
                product=Product.PLUS, reason="r", summary="s", recommended_action="a",
            ))
            first.save_receipt("C-1", "c-8f2a", {"reply": "stored verbatim"})
            first.save_run(_run("ar-1", "C-1", "c-8f2a", "2026-09-22T10:00:00"))
            first.close()

            second = SqliteRepository(path)
            try:
                self.assertEqual(second.get_receipt("C-1", "c-8f2a"), {"reply": "stored verbatim"})
                self.assertEqual(second.get_opportunity("C-1").customer_message_count, 3)
                self.assertEqual(second.active_case_for("C-1").reason, "r")
                self.assertEqual(second.list_runs(client_message_id="c-8f2a")[0]["run_id"], "ar-1")
            finally:
                second.close()

    def test_pending_handoff_and_structured_answers_survive_reopen(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.db"
            first = SqliteRepository(path)
            opportunity = _opportunity()
            opportunity.pending_handoff_reason = "needs a representative"
            opportunity.pending_question_field = "budget"
            opportunity.collected_answers = {"budget": "1000"}
            opportunity.evidence_sources = {"budget": "customer message"}
            first.upsert_opportunity(opportunity)
            first.close()

            second = SqliteRepository(path)
            try:
                loaded = second.get_opportunity("C-1")
                self.assertEqual("needs a representative", loaded.pending_handoff_reason)
                self.assertEqual("budget", loaded.pending_question_field)
                self.assertEqual({"budget": "1000"}, loaded.collected_answers)
                self.assertEqual({"budget": "customer message"}, loaded.evidence_sources)
                self.assertEqual({"intent": "application"}, loaded.score_history[0].evidence)
            finally:
                second.close()

    def test_memory_and_indexed_messages_survive_reopen(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "memory.db"
            first = SqliteRepository(path)
            opportunity = _opportunity()
            memory = {
                "version": 1,
                "facts": [{"text": "Prefers email", "source_message_ids": ["msg-source"]}],
                "covered_message_ids": ["msg-source"],
                "through_message_id": "msg-source",
                "updated_at": "2026-09-25T10:00:00",
            }
            opportunity.messages.append(Message.from_customer("Please contact me by email.", id="msg-source"))
            first.save_turn(opportunity, _run("ar-memory", "C-1", "k-memory", "2026-09-25T10:00:00"), memory=memory)
            first.close()

            second = SqliteRepository(path)
            try:
                self.assertEqual(memory, second.get_memory("C-1"))
                self.assertEqual("msg-source", second.search_messages("C-1", "contact me by email")[0]["message_id"])
            finally:
                second.close()

    def test_legacy_opportunity_payload_is_lazily_added_to_search_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "legacy.db"
            repo = SqliteRepository(path)
            opportunity = _opportunity()
            first_message_id = opportunity.messages[0].id
            repo.upsert_opportunity(opportunity)
            with repo._conn:
                repo._conn.execute("DELETE FROM messages WHERE opportunity_id = ?", ("C-1",))
            repo.close()

            reopened = SqliteRepository(path)
            try:
                results = reopened.search_messages("C-1", "hi")
                self.assertEqual(first_message_id, results[0]["message_id"])
                self.assertEqual(3, reopened._conn.execute(
                    "SELECT COUNT(*) FROM messages WHERE opportunity_id = ?", ("C-1",)
                ).fetchone()[0])
            finally:
                reopened.close()

    def test_migrations_are_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "m.db"
            SqliteRepository(path).close()
            repo = SqliteRepository(path)
            try:
                versions = [r[0] for r in repo._conn.execute("SELECT version FROM schema_version")]
                self.assertEqual(versions, [1, 2])
            finally:
                repo.close()

    def test_agent_run_columns_and_totals_match_the_payload(self):
        repo = SqliteRepository(":memory:")
        run = _run("ar-metrics", "C-1", "k-metrics", "2026-09-22T10:00:00")
        run.update({
            "duration_ms": 42,
            "totals": {"total_tokens": 123, "cost": {"amount": 0.125, "currency": "USD"}},
            "llm_calls": [
                {"total_tokens": 123, "cost": {"amount": 0.125, "currency": "USD"}},
                {"total_tokens": 0},
            ],
        })
        try:
            repo.save_run(run)
            row = repo._conn.execute(
                "SELECT duration_ms, total_tokens, cost_amount, cost_currency, pricing_known "
                "FROM agent_runs WHERE run_id = ?", ("ar-metrics",)
            ).fetchone()
            self.assertEqual((42, 123, 0.125, "USD", 0), tuple(row))
            totals = repo.conversation_totals("C-1")
            self.assertEqual(123, totals["total_tokens"])
            self.assertEqual(0.125, totals["cost"]["amount"])
            self.assertFalse(totals["cost"]["pricing_known"])
        finally:
            repo.close()

    def test_turn_write_failure_rolls_back_every_record(self):
        repo = SqliteRepository(":memory:")
        original = _opportunity()
        original.customer_message_count = 3
        repo.upsert_opportunity(original)

        changed = _opportunity()
        changed.customer_message_count = 4
        changed.messages.append(Message.from_customer("only in the failed transaction", id="txn-only"))
        case = HumanCase(
            opportunity_id="C-1", customer_name="Sarah", state=OpportunityState.HIGH_INTENT,
            product=Product.PLUS, reason="r", summary="s", recommended_action="a",
        )
        run = _run("ar-turn", "C-1", "k-turn", "2026-09-22T10:00:00")
        receipt = {"client_message_id": "k-turn", "reply": "saved"}
        memory = {"version": 1, "facts": [], "covered_message_ids": [], "through_message_id": None}
        try:
            with patch.object(repo, "_write_receipt", side_effect=RuntimeError("simulated failure")):
                with self.assertRaisesRegex(RuntimeError, "simulated failure"):
                    repo.save_turn(changed, run, case=case, receipt=receipt, memory=memory)
            self.assertEqual(3, repo.get_opportunity("C-1").customer_message_count)
            self.assertIsNone(repo.get_case(case.id))
            self.assertIsNone(repo.get_run("ar-turn"))
            self.assertIsNone(repo.get_receipt("C-1", "k-turn"))
            self.assertIsNone(repo.get_memory("C-1"))
            self.assertEqual([], repo.search_messages("C-1", "only in the failed transaction"))
        finally:
            repo.close()
