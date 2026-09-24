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
        score_history=[ScoreHistoryEntry(datetime(2026, 9, 22, 12, 0), 45, "Cold Lead", "message(rule)")],
        state_history=[StateHistoryEntry(datetime(2026, 9, 22, 12, 0), "Cold Lead", "High Intent", "purchase")],
        human_takeover=True,
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

    def test_message_ids_and_timestamps_are_preserved_exactly(self):
        original = _opportunity()
        self.repo.upsert_opportunity(original)
        loaded = self.repo.get_opportunity("C-1")
        self.assertEqual([m.id for m in loaded.messages], [m.id for m in original.messages])
        self.assertEqual([m.ts for m in loaded.messages], [m.ts for m in original.messages])
        self.assertEqual(loaded.messages[2].rep_name, "Ana")
        self.assertEqual(loaded.messages[1].generation_value, "template")

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

    def test_migrations_are_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "m.db"
            SqliteRepository(path).close()
            repo = SqliteRepository(path)
            try:
                versions = [r[0] for r in repo._conn.execute("SELECT version FROM schema_version")]
                self.assertEqual(versions, [1])
            finally:
                repo.close()
