# -*- coding: utf-8 -*-
"""P5: the human actions — rep reply, case status, disqualify/release."""
from __future__ import annotations

import unittest

from backend import config
from backend.agent.extraction import build_extractor
from backend.agent.reply import build_composer
from backend.domain.enums import CaseStatus, Generation, MessageAuthor, MessageRole, Qualification
from backend.services import CaseNotFound, InvalidTransition, NotUnderTakeover, OpportunityNotFound, cases
from backend.services.analytics import compute_analytics, health
from backend.services.conversation import ConversationService
from backend.services.rep_reply import append_rep_reply
from backend.services.seeding import SCRIPT, render_summary, seed
from backend.storage import MemoryRepository


class _Base(unittest.TestCase):
    def setUp(self):
        self._trace = config.CONSOLE_TRACE
        config.CONSOLE_TRACE = False
        self.svc = ConversationService(
            MemoryRepository(), extractor=build_extractor(None), composer=build_composer(None)
        )
        self.repo = self.svc.repo

    def tearDown(self):
        config.CONSOLE_TRACE = self._trace

    def _escalated(self):
        self.svc.handle_customer_message("C-1", "Sarah", "How much does CareSure Plus cost?")
        return self.svc.handle_customer_message("C-1", "Sarah", "Can you give me a discount?")


class TestRepReply(_Base):
    def test_under_takeover_appends_a_human_message_and_runs_no_pipeline(self):
        before = self._escalated().opportunity
        count, transcript, history, state = (
            before.customer_message_count, len(before.messages), len(before.score_history), before.state
        )
        message = append_rep_reply(self.repo, "C-1", text="Hi Sarah, Ana here.", rep_name="Ana", client_message_id="r1")
        after = self.repo.get_opportunity("C-1")

        self.assertEqual((message.role, message.author, message.generation), (MessageRole.BUSINESS, MessageAuthor.HUMAN, Generation.HUMAN))
        self.assertEqual(message.rep_name, "Ana")
        self.assertEqual(after.messages[-1].id, message.id)
        self.assertEqual(after.customer_message_count, count)
        self.assertEqual(len(after.messages), transcript + 1)
        self.assertEqual(len(after.score_history), history)
        self.assertEqual(after.state, state)
        self.assertEqual(len(self.repo.list_runs(opportunity_id="C-1")), 2)

    def test_not_under_takeover_is_refused_and_appends_nothing(self):
        self.svc.handle_customer_message("C-1", "Sarah", "How much does CareSure Plus cost?")
        before = len(self.repo.get_opportunity("C-1").messages)
        with self.assertRaises(NotUnderTakeover):
            append_rep_reply(self.repo, "C-1", text="hello")
        self.assertEqual(len(self.repo.get_opportunity("C-1").messages), before)

    def test_unknown_opportunity(self):
        with self.assertRaises(OpportunityNotFound):
            append_rep_reply(self.repo, "nope", text="hello")


class TestCaseStatus(_Base):
    def test_parse_status_accepts_names_and_values(self):
        self.assertEqual(cases.parse_status("TAKEN_OVER"), CaseStatus.TAKEN_OVER)
        self.assertEqual(cases.parse_status("Taken Over"), CaseStatus.TAKEN_OVER)
        self.assertEqual(cases.parse_status("taken-over"), CaseStatus.TAKEN_OVER)
        with self.assertRaises(InvalidTransition):
            cases.parse_status("resolved")

    def test_closing_clears_the_takeover_flags(self):
        case = self._escalated().case
        cases.set_status(self.repo, case.id, CaseStatus.TAKEN_OVER)
        self.assertEqual(self.repo.get_case(case.id).status, CaseStatus.TAKEN_OVER)
        self.assertTrue(self.repo.get_opportunity("C-1").human_takeover)

        cases.set_status(self.repo, case.id, CaseStatus.CLOSED)
        opp = self.repo.get_opportunity("C-1")
        self.assertFalse(opp.human_takeover)
        self.assertFalse(opp.human_intervention_required)
        self.assertIsNone(self.repo.active_case_for("C-1"))

    def test_a_new_reason_updates_the_open_case_rather_than_opening_another(self):
        case = self._escalated().case
        self.svc.handle_customer_message("C-1", "Sarah", "I want to speak to a real person.")
        self.assertEqual(len(self.repo.list_cases()), 1)
        self.assertIn("[Update]", self.repo.get_case(case.id).summary)

    def test_unknown_case(self):
        with self.assertRaises(CaseNotFound):
            cases.set_status(self.repo, "H-NOPE", CaseStatus.CLOSED)


class TestQualificationActions(_Base):
    def test_disqualify_is_a_human_action_and_release_restores(self):
        self.svc.handle_customer_message("C-1", "Sarah", "How much does CareSure Plus cost?")
        opp = cases.disqualify(self.repo, "C-1", reason="Duplicate account")
        self.assertEqual(opp.qualification, Qualification.DISQUALIFIED)
        self.assertEqual(self.repo.get_opportunity("C-1").qualification_reason, "Duplicate account")

        opp = cases.release(self.repo, "C-1")
        self.assertEqual(opp.qualification, Qualification.QUALIFIED)
        self.assertEqual(opp.solicitation_count, 0)


class TestSeedingAndAnalytics(_Base):
    def test_seed_is_idempotent_and_feeds_analytics(self):
        first = seed(self.svc)
        self.assertTrue(first["seeded"])
        self.assertEqual(first["customers_seeded"], len(SCRIPT))
        self.assertEqual(first["messages_seeded"], sum(len(t) for _, _, t in SCRIPT))
        self.assertFalse(seed(self.svc)["seeded"])

        summary = compute_analytics(self.repo)
        self.assertEqual(summary["total_opportunities"], len(SCRIPT))
        self.assertEqual(sum(summary["by_state"].values()), len(SCRIPT))
        self.assertEqual(sum(summary["by_qualification"].values()), len(SCRIPT))
        self.assertEqual(summary["human_cases_total"], len(self.repo.list_cases()))
        self.assertEqual(health(self.repo)["opportunities"], len(SCRIPT))
        self.assertIn("SALES DASHBOARD", render_summary(self.repo))
