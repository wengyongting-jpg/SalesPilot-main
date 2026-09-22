# -*- coding: utf-8 -*-
"""P5a: persistence, run in parity across both repositories.

Every behavioural test here runs against **both** the in-memory repository and the
SQLite one. That is the design of the file, not a convenience: the rest of the suite
uses the in-memory repository for speed, and those tests only mean something if the
two implementations genuinely agree. A parity suite is what makes the cheap
substitution honest.

The idempotency criteria come from `docs/backend-contract.md` Part B item 1, whose
failure mode is silent score inflation rather than an exception — which is why the
receipt has to survive a restart, and why that is tested by actually closing the
connection and opening a new one rather than by trusting that it would.
"""
from __future__ import annotations

import shutil
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from backend.domain.case import HumanCase
from backend.domain.enums import (
    CaseStatus,
    Generation,
    Intent,
    OpportunityState,
    Priority,
    Product,
    Qualification,
    Signal,
)
from backend.domain.message import Message
from backend.domain.opportunity import (
    Opportunity,
    ScoreCard,
    ScoreHistoryEntry,
    StateHistoryEntry,
)

NOW = datetime(2026, 9, 22, 12, 0, 0)


def full_opportunity() -> Opportunity:
    """An opportunity with every field populated, including the ones added in P1-P2.

    Deliberately exhaustive: a round-trip test that only exercises the fields the
    author remembered is how a new column silently stops being persisted.
    """
    opp = Opportunity(
        id="C-1024",
        customer_name="Sarah",
        state=OpportunityState.HIGH_INTENT,
        product=Product.PLUS,
        created_at=NOW - timedelta(days=2),
        updated_at=NOW,
    )
    opp.signals = [Signal.PURCHASE, Signal.COMPETITIVE]
    opp.signal_history = [Signal.HESITATION, Signal.PURCHASE, Signal.COMPETITIVE]
    opp.main_concern = "Price versus a competitor"
    opp.competitive_risk = True
    opp.churn_risk = False
    opp.compliance_risk = False
    opp.expansion = ["Family"]
    opp.last_intent = Intent.APPLICATION
    opp.best_intent = Intent.APPLICATION
    opp.urgency_observed = True
    opp.customer_message_count = 4
    opp.qualification = Qualification.QUALIFIED
    opp.qualification_reason = None
    opp.solicitation_count = 1
    opp.human_takeover = True
    opp.human_intervention_required = True
    opp.score = ScoreCard(
        need_identified=40, product_potential=30, expansion=13, fit_total=83,
        purchase_intent=37, purchase_readiness=27, engagement=18,
        engagement_depth=18, engagement_urgency=6, engagement_recency=95,
        behaviour_raw=82, behaviour_total=78, total=81, priority=Priority.HIGH,
    )
    opp.score_history = [
        ScoreHistoryEntry(timestamp=NOW - timedelta(hours=2), score=45,
                          state="Potential Interest", trigger="message(llm)"),
        ScoreHistoryEntry(timestamp=NOW, score=81, state="High Intent",
                          trigger="message(llm)"),
    ]
    opp.state_history = [
        StateHistoryEntry(timestamp=NOW, from_state="Evaluation & Hesitation",
                          to_state="High Intent", reason="Strong purchase preparation"),
    ]
    opp.messages = [
        Message.from_customer("How much is Plus?", id="m-1",
                              ts=NOW - timedelta(minutes=30), client_message_id="c-1"),
        Message.from_ai("From S$1,500/year.", id="m-2",
                        ts=NOW - timedelta(minutes=29), generation=Generation.LLM),
        Message.from_ai("Offline notice.", id="m-3",
                        ts=NOW - timedelta(minutes=20), generation=Generation.TEMPLATE),
        Message.from_human("Alex here, happy to help.", id="m-4",
                           ts=NOW - timedelta(minutes=10), rep_name="Alex",
                           client_message_id="r-1"),
        Message.from_system("A representative has taken over.", id="m-5", ts=NOW),
    ]
    return opp


def a_case() -> HumanCase:
    return HumanCase(
        id="H-ABC123",
        opportunity_id="C-1024",
        customer_name="Sarah",
        state=OpportunityState.HIGH_INTENT,
        product=Product.PLUS,
        reason="High purchase intent with competitive comparison",
        summary="Customer is comparing with another insurer.",
        recommended_action="Human sales intervention: address the competitive risk",
        created_at=NOW,
    )


def a_run(run_id: str, *, client_message_id: str | None = None, tokens: int = 500,
          cost: float = 0.0002):
    from backend.observability.pricing import Money
    from backend.observability.run import AgentRun, Content, LlmCall, RunStatus

    run = AgentRun(
        run_id=run_id,
        opportunity_id="C-1024",
        client_message_id=client_message_id,
        customer_message_count=3,
        started_at=NOW,
        finished_at=NOW + timedelta(milliseconds=1240),
        duration_ms=1240,
        status=RunStatus.OK,
    )
    run.llm_calls.append(
        LlmCall(index=0, purpose="extraction", model="gpt-4o-mini", duration_ms=800,
                prompt_tokens=tokens - 100, completion_tokens=100,
                cost=Money(amount=cost), input=Content(chars=10, content="in"),
                output=Content(chars=5, content="out"))
    )
    return run


class RepositoryParityTests:
    """Shared behaviour. Mixed into one test case per implementation."""

    def make_repository(self):
        raise NotImplementedError

    def reopen(self, repository):
        """Return a repository reading the same underlying store.

        For SQLite that means closing and reconnecting, which is the only way to test
        that something was really written rather than merely remembered.
        """
        return repository

    def setUp(self):
        self.repo = self.make_repository()

    # ---- Opportunities ---------------------------------------------------

    def test_an_opportunity_round_trips_with_every_field(self):
        original = full_opportunity()
        self.repo.upsert_opportunity(original)
        loaded = self.reopen(self.repo).get_opportunity("C-1024")

        self.assertIsNotNone(loaded)
        self.assertEqual(original.customer_name, loaded.customer_name)
        self.assertIs(original.state, loaded.state)
        self.assertIs(original.product, loaded.product)
        self.assertEqual(original.signals, loaded.signals)
        self.assertEqual(original.signal_history, loaded.signal_history)
        self.assertEqual(original.main_concern, loaded.main_concern)
        self.assertEqual(original.competitive_risk, loaded.competitive_risk)
        self.assertEqual(original.expansion, loaded.expansion)
        self.assertIs(original.best_intent, loaded.best_intent)
        self.assertEqual(original.urgency_observed, loaded.urgency_observed)
        self.assertEqual(original.customer_message_count, loaded.customer_message_count)
        self.assertIs(original.qualification, loaded.qualification)
        self.assertEqual(original.solicitation_count, loaded.solicitation_count)
        self.assertEqual(original.human_takeover, loaded.human_takeover)

    def test_the_two_axis_score_round_trips_dimension_by_dimension(self):
        """A score stored as a single total would lose exactly what the redesign
        added."""
        self.repo.upsert_opportunity(full_opportunity())
        score = self.reopen(self.repo).get_opportunity("C-1024").score
        self.assertEqual(83, score.fit_total)
        self.assertEqual(78, score.behaviour_total)
        self.assertEqual(82, score.behaviour_raw)
        self.assertEqual(95, score.engagement_recency)
        self.assertEqual(18, score.engagement_depth)
        self.assertEqual(6, score.engagement_urgency)
        self.assertIs(Priority.HIGH, score.priority)

    def test_all_three_message_axes_round_trip(self):
        """`role`, `author` and `generation` are three separate questions. Losing any
        one of them makes an impossible message representable again."""
        self.repo.upsert_opportunity(full_opportunity())
        messages = self.reopen(self.repo).get_opportunity("C-1024").messages
        self.assertEqual(
            [
                ("customer", None, None),
                ("business", "ai", "llm"),
                ("business", "ai", "template"),
                ("business", "human", "human"),
                ("business", "system", "template"),
            ],
            [(m.role.value, m.author_value, m.generation_value) for m in messages],
        )
        self.assertEqual("Alex", messages[3].rep_name)
        self.assertEqual("c-1", messages[0].client_message_id)

    def test_messages_keep_their_ids_and_their_order(self):
        self.repo.upsert_opportunity(full_opportunity())
        messages = self.reopen(self.repo).get_opportunity("C-1024").messages
        self.assertEqual(["m-1", "m-2", "m-3", "m-4", "m-5"],
                         [m.id for m in messages])

    def test_histories_round_trip(self):
        self.repo.upsert_opportunity(full_opportunity())
        loaded = self.reopen(self.repo).get_opportunity("C-1024")
        self.assertEqual([45, 81], [entry.score for entry in loaded.score_history])
        self.assertEqual("High Intent", loaded.state_history[0].to_state)

    def test_an_upsert_replaces_rather_than_duplicating(self):
        opp = full_opportunity()
        self.repo.upsert_opportunity(opp)
        opp.customer_message_count = 9
        opp.messages.append(Message.from_customer("another", id="m-6", ts=NOW))
        self.repo.upsert_opportunity(opp)

        repo = self.reopen(self.repo)
        self.assertEqual(1, len(repo.list_opportunities()))
        loaded = repo.get_opportunity("C-1024")
        self.assertEqual(9, loaded.customer_message_count)
        self.assertEqual(6, len(loaded.messages))

    def test_an_unknown_opportunity_is_none_not_an_error(self):
        self.assertIsNone(self.repo.get_opportunity("C-nope"))

    def test_deleting_is_idempotent(self):
        self.repo.upsert_opportunity(full_opportunity())
        self.repo.delete_opportunity("C-1024")
        self.repo.delete_opportunity("C-1024")
        self.assertIsNone(self.reopen(self.repo).get_opportunity("C-1024"))

    def test_deleting_removes_the_messages_too(self):
        """Otherwise a reset conversation comes back with its old transcript."""
        self.repo.upsert_opportunity(full_opportunity())
        self.repo.delete_opportunity("C-1024")
        self.repo.upsert_opportunity(
            Opportunity(id="C-1024", customer_name="Sarah")
        )
        loaded = self.reopen(self.repo).get_opportunity("C-1024")
        self.assertEqual([], loaded.messages)

    # ---- Incremental reads ----------------------------------------------

    def test_messages_since_a_message_id_returns_only_newer_ones(self):
        """`interface-v1.md` §5.6 and gap register item 12."""
        self.repo.upsert_opportunity(full_opportunity())
        newer = self.reopen(self.repo).messages_since("C-1024", cursor="m-3")
        self.assertEqual(["m-4", "m-5"], [m.id for m in newer])

    def test_messages_since_a_timestamp_returns_only_newer_ones(self):
        """The cursor is exclusive, and the timestamp used is a real message's own —
        which is what a poller actually has to hand."""
        self.repo.upsert_opportunity(full_opportunity())
        third = (NOW - timedelta(minutes=20)).isoformat()   # m-3
        newer = self.reopen(self.repo).messages_since("C-1024", cursor=third)
        self.assertEqual(["m-4", "m-5"], [m.id for m in newer])

    def test_a_timestamp_between_two_messages_returns_everything_after_it(self):
        self.repo.upsert_opportunity(full_opportunity())
        between = (NOW - timedelta(minutes=25)).isoformat()  # after m-2, before m-3
        newer = self.reopen(self.repo).messages_since("C-1024", cursor=between)
        self.assertEqual(["m-3", "m-4", "m-5"], [m.id for m in newer])

    def test_no_cursor_returns_the_whole_transcript(self):
        self.repo.upsert_opportunity(full_opportunity())
        self.assertEqual(
            5, len(self.reopen(self.repo).messages_since("C-1024", cursor=None))
        )

    def test_a_future_cursor_returns_nothing(self):
        self.repo.upsert_opportunity(full_opportunity())
        self.assertEqual(
            [],
            self.reopen(self.repo).messages_since(
                "C-1024", cursor="2099-01-01T00:00:00"
            ),
        )

    def test_an_unparsable_cursor_is_rejected_rather_than_ignored(self):
        """Silently returning everything would make a broken client look healthy."""
        self.repo.upsert_opportunity(full_opportunity())
        with self.assertRaises(ValueError):
            self.repo.messages_since("C-1024", cursor="not-a-cursor")

    def test_history_reads_can_be_bounded(self):
        """Gap register item 12: unbounded history arrays make an admin poll grow with
        the conversation."""
        self.repo.upsert_opportunity(full_opportunity())
        loaded = self.reopen(self.repo).get_opportunity("C-1024", history_limit=1)
        self.assertEqual(1, len(loaded.score_history))
        self.assertEqual(81, loaded.score_history[0].score, "keep the most recent")

    # ---- Cases -----------------------------------------------------------

    def test_a_case_round_trips(self):
        self.repo.add_case(a_case())
        loaded = self.reopen(self.repo).list_cases()
        self.assertEqual(1, len(loaded))
        self.assertEqual("H-ABC123", loaded[0].id)
        self.assertIs(CaseStatus.OPEN, loaded[0].status)
        self.assertIs(OpportunityState.HIGH_INTENT, loaded[0].state)

    def test_updating_a_case_does_not_create_a_second_one(self):
        case = a_case()
        self.repo.add_case(case)
        case.status = CaseStatus.TAKEN_OVER
        self.repo.update_case(case)
        cases = self.reopen(self.repo).list_cases()
        self.assertEqual(1, len(cases))
        self.assertIs(CaseStatus.TAKEN_OVER, cases[0].status)

    def test_an_active_case_can_be_found_for_an_opportunity(self):
        self.repo.add_case(a_case())
        repo = self.reopen(self.repo)
        self.assertIsNotNone(repo.active_case_for("C-1024"))

        case = repo.active_case_for("C-1024")
        case.status = CaseStatus.CLOSED
        repo.update_case(case)
        self.assertIsNone(self.reopen(repo).active_case_for("C-1024"))

    # ---- Idempotency receipts -------------------------------------------

    def test_an_unseen_key_has_no_receipt(self):
        self.assertIsNone(self.repo.get_message_receipt("C-1024", "k1"))

    def test_a_receipt_round_trips(self):
        self.repo.save_message_receipt("C-1024", "k1", {"reply": "hello"})
        self.assertEqual(
            {"reply": "hello"},
            self.reopen(self.repo).get_message_receipt("C-1024", "k1"),
        )

    def test_receipts_are_scoped_to_the_conversation(self):
        self.repo.save_message_receipt("C-1024", "k1", {"reply": "a"})
        repo = self.reopen(self.repo)
        self.assertIsNone(repo.get_message_receipt("C-other", "k1"))

    # ---- Agent runs ------------------------------------------------------

    def test_an_agent_run_round_trips(self):
        self.repo.save_agent_run(a_run("ar-1", client_message_id="c-1"))
        loaded = self.reopen(self.repo).get_agent_run("ar-1")
        self.assertIsNotNone(loaded)
        self.assertEqual("ar-1", loaded["run_id"])
        self.assertEqual(1240, loaded["duration_ms"])
        self.assertEqual(500, loaded["totals"]["total_tokens"])

    def test_runs_are_retained_per_message_not_just_the_latest(self):
        """`interface-v1.md` §5.3 item 5: the Inbox shows history, not one exchange."""
        for index in range(3):
            self.repo.save_agent_run(a_run(f"ar-{index}"))
        self.assertEqual(3, len(self.reopen(self.repo).list_agent_runs("C-1024")))

    def test_runs_are_queryable_by_client_message_id(self):
        """The telemetry correlation key from `interface-v1.md` §3."""
        self.repo.save_agent_run(a_run("ar-a", client_message_id="c-8f2a"))
        self.repo.save_agent_run(a_run("ar-b", client_message_id="c-other"))
        found = self.reopen(self.repo).list_agent_runs(
            "C-1024", client_message_id="c-8f2a"
        )
        self.assertEqual(["ar-a"], [run["run_id"] for run in found])

    def test_runs_come_back_newest_first_and_can_be_limited(self):
        for index in range(5):
            self.repo.save_agent_run(a_run(f"ar-{index}"))
        found = self.reopen(self.repo).list_agent_runs("C-1024", limit=2)
        self.assertEqual(2, len(found))

    def test_conversation_totals_sum_tokens_and_cost(self):
        """§5.3 item 6: a running total per conversation."""
        self.repo.save_agent_run(a_run("ar-1", tokens=500, cost=0.0002))
        self.repo.save_agent_run(a_run("ar-2", tokens=300, cost=0.0001))
        totals = self.reopen(self.repo).conversation_totals("C-1024")
        self.assertEqual(2, totals["run_count"])
        self.assertEqual(800, totals["total_tokens"])
        self.assertAlmostEqual(0.0003, totals["cost"]["amount"], places=8)

    def test_totals_for_an_unknown_conversation_are_zero_not_an_error(self):
        totals = self.repo.conversation_totals("C-nope")
        self.assertEqual(0, totals["run_count"])
        self.assertEqual(0, totals["total_tokens"])


class TestInMemoryRepository(RepositoryParityTests, unittest.TestCase):
    def make_repository(self):
        from backend.storage.memory import InMemoryRepository

        return InMemoryRepository()

    def test_it_does_not_hand_out_its_own_objects(self):
        """A caller mutating a returned opportunity must not silently change the
        store, or the in-memory repository would behave unlike the SQLite one and
        every test using it would be measuring the wrong thing."""
        self.repo.upsert_opportunity(full_opportunity())
        loaded = self.repo.get_opportunity("C-1024")
        loaded.customer_message_count = 999
        self.assertEqual(4, self.repo.get_opportunity("C-1024").customer_message_count)


class TestSqliteRepository(RepositoryParityTests, unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = Path(self.tmpdir) / "backend.db"
        self._open: list = []
        super().setUp()

    def tearDown(self):
        for repository in self._open:
            try:
                repository.close()
            except Exception:
                pass
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def make_repository(self):
        from backend.storage.sqlite import SqliteRepository

        repository = SqliteRepository(self.db_path)
        self._open.append(repository)
        return repository

    def reopen(self, repository):
        """Close and reconnect, so only what was really written survives."""
        repository.close()
        return self.make_repository()

    def test_a_receipt_survives_a_restart(self):
        """The acceptance criterion that matters most: a retry usually happens
        because the client never saw the response, and a deploy or a crash looks
        exactly like that."""
        self.repo.save_message_receipt("C-1024", "k-restart", {"reply": "hello"})
        self.repo.close()

        reconnected = self.make_repository()
        self.assertEqual(
            {"reply": "hello"},
            reconnected.get_message_receipt("C-1024", "k-restart"),
        )

    def test_opening_an_existing_database_twice_is_safe(self):
        self.repo.upsert_opportunity(full_opportunity())
        self.repo.close()
        again = self.make_repository()
        self.assertIsNotNone(again.get_opportunity("C-1024"))

    def test_the_database_file_is_created_with_its_parent_directory(self):
        nested = Path(self.tmpdir) / "deeper" / "still" / "backend.db"
        from backend.storage.sqlite import SqliteRepository

        repository = SqliteRepository(nested)
        self._open.append(repository)
        self.assertTrue(nested.exists())


if __name__ == "__main__":
    unittest.main()
