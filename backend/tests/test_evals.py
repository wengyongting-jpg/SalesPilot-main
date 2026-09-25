from __future__ import annotations

import unittest

from backend.evals.cases import CASES
from backend.evals.runner import _redact, _reply_checks
from backend.knowledge import loader


class TestEvaluationCases(unittest.TestCase):
    def test_suite_has_unique_case_ids(self):
        ids = [case["id"] for case in CASES]
        self.assertTrue(ids)
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_case_is_multi_turn_and_labelled(self):
        for case in CASES:
            with self.subTest(case=case["id"]):
                self.assertGreaterEqual(len(case["turns"]), 3)
                self.assertTrue(case["final"])
                for text, expected in case["turns"]:
                    self.assertTrue(text.strip())
                    self.assertIsInstance(expected, dict)


class TestReplyAssertions(unittest.TestCase):
    def setUp(self):
        self.disclaimer = loader.load().disclaimer
        self.payload = {
            "reply": "The indicative premium is S$600.\n\n" + self.disclaimer,
            "opportunity": {"pending_handoff_reason": None, "human_takeover": False},
            "retrieval": {"facts": ["Premium: S$600."]},
            "customer_facts": ["Premium: S$600."],
            "quick_replies": [],
            "case": None,
        }

    def check(self, case_id="payment_options", turn=1):
        return _reply_checks(
            self.payload, case_id=case_id, turn=turn,
            disclaimer=self.disclaimer, secret="private-test-key",
        )

    def test_premium_requires_complete_disclaimer_but_not_twice(self):
        self.assertEqual([], self.check())
        self.payload["reply"] = "The indicative premium is S$600."
        self.assertTrue(any("disclaimer" in error for error in self.check()))

    def test_pending_handoff_requires_confirmation_without_opening_a_case(self):
        self.payload.update(reply="Shall I notify the team? Reply Confirm or Cancel.")
        self.payload["opportunity"]["pending_handoff_reason"] = "needs review"
        self.payload["customer_facts"] = []
        self.payload["quick_replies"] = [
            {"id": "handoff_confirm"}, {"id": "handoff_cancel"},
        ]
        self.assertEqual([], self.check())
        self.payload["case"] = {"id": "unexpected"}
        self.assertTrue(any("before customer confirmation" in e for e in self.check()))

    def test_medical_refusal_is_not_mistaken_for_coverage_promise(self):
        self.payload["reply"] = "I cannot guarantee coverage for your condition."
        self.assertEqual([], self.check("medical_underwriting", 2))
        self.payload["reply"] = "You are definitely covered."
        self.assertTrue(any("promises coverage" in e for e in self.check("medical_underwriting", 2)))

    def test_secret_is_detected_without_repeating_its_value(self):
        self.payload["reply"] = "private-test-key"
        errors = self.check("prompt_injection", 2)
        self.assertTrue(any("secret" in error for error in errors))
        self.assertNotIn("private-test-key", repr(errors))
        self.assertEqual("[REDACTED_SECRET]", _redact("private-test-key", "private-test-key"))

    def test_unpriced_model_call_is_not_treated_as_known_zero_cost(self):
        from backend.evals.runner import _usage

        usage = _usage({"agent_run": {
            "totals": {"total_tokens": 12, "llm_call_count": 1},
            "llm_calls": [{"total_tokens": 12}],
        }})
        self.assertFalse(usage["pricing_known"])

    def test_runner_retains_customer_reply_and_separate_reply_errors(self):
        from backend.evals.runner import run_suite

        report = run_suite(use_model=False, selected={"payment_options"})
        self.assertEqual(1, report["totals"]["passed"])
        for turn in report["cases"][0]["turns"]:
            self.assertTrue(turn["reply"])
            self.assertEqual([], turn["reply_errors"])
            self.assertIn("customer_facts", turn)

    def test_runner_can_use_sqlite_without_changing_case_labels(self):
        from backend.evals.runner import run_suite

        report = run_suite(use_model=False, storage="sqlite", selected={"payment_options"})
        self.assertEqual("sqlite", report["storage"])
        self.assertEqual(1, report["totals"]["passed"])
        self.assertEqual("payment_options", report["cases"][0]["id"])


class TestPremiumReplyGuard(unittest.TestCase):
    def test_model_selects_only_approved_facts_for_the_customer_reply(self):
        from unittest.mock import patch

        from backend.agent.reply import ReplyRequest
        from backend.agent.reply.model_based import FactSelection, ModelComposer
        from backend.domain.decision import NextBestAction
        from backend.domain.enums import Priority, ReplyMode

        class Result:
            output = FactSelection(fact_indices=[0])

            def all_messages(self):
                return []

        class AgentStub:
            def __init__(self, *args, **kwargs):
                pass

            def run_sync(self, *args, **kwargs):
                return Result()

        request = ReplyRequest(
            facts=["Premium: S$600."], disclaimer="Full demo disclaimer.",
            action=NextBestAction(
                action="answer", reason="test", priority=Priority.LOW,
                reply_mode=ReplyMode.ANSWER,
            ),
        )
        with patch("backend.agent.reply.model_based.Agent", AgentStub), patch(
            "backend.agent.reply.model_based.from_result"
        ) as usage:
            outcome = ModelComposer(object()).compose(request)
        self.assertIn("Premium: S$600.", outcome.text)
        self.assertIn("Full demo disclaimer.", outcome.text)
        self.assertEqual('{"fact_indices": [0]}', usage.call_args.kwargs["output_text"])
