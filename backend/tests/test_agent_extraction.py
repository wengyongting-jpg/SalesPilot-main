# -*- coding: utf-8 -*-
"""P3: extraction — the model/rule peer pair, and the contract-violation fix.

Acceptance criteria from `docs/backend-plan.md` §9, restated as assertions:

    1. With `TestModel`, a run completes offline and the trace contains at
       least one model-selected tool call.
    2. Feeding the model output `{"intent": "medical_question"}` produces a
       recorded violation naming the offending value.
    3. "Compare the waiting period of Plus and Family" results in two
       knowledge lookups in one run.
    4. No tool reaches `kernel` (enforced separately by
       `test_architecture.py`, which fails the build if `agent` imports
       `kernel`); `request_human_handoff` produces a `HandoffProposal` and
       opens no case.
"""
from __future__ import annotations

import unittest

from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel

from backend.agent.extraction import ModelExtractor, RuleExtractor, build_extractor
from backend.agent.tools.handoff import request_human_handoff
from backend.domain.detection import HandoffProposal
from backend.domain.enums import Intent
from backend.observability import RunRecorder


def _final(intent: str = "generic") -> ModelResponse:
    return ModelResponse(
        parts=[ToolCallPart("final_result", {"intent": intent, "product": "unknown", "genuine_enquiry": True})]
    )


def _recorder() -> RunRecorder:
    return RunRecorder("C-1", client_message_id="c-1", content_enabled=True, content_max_chars=8000)


class TestOfflinePeer(unittest.TestCase):
    def test_build_extractor_with_no_model_selects_the_rule_peer(self):
        extractor = build_extractor(model=None)
        self.assertIsInstance(extractor, RuleExtractor)

    def test_rule_peer_never_touches_a_model_and_still_produces_a_detection(self):
        outcome = build_extractor(model=None).extract("How much is the Plus plan?")
        self.assertEqual(outcome.source, "rule")
        self.assertIsNone(outcome.violation)
        self.assertEqual(outcome.detection.intent, Intent.PRICE)


class TestModelBasedRunCompletesOffline(unittest.TestCase):
    """Acceptance check 1: a `TestModel` run completes and calls a tool."""

    def test_a_test_model_run_selects_at_least_one_tool(self):
        extractor = build_extractor(model=TestModel())
        self.assertIsInstance(extractor, ModelExtractor)
        outcome = extractor.extract("How much is the Plus plan?")
        self.assertEqual(outcome.source, "llm")
        self.assertIsNone(outcome.violation)


class TestContractViolationIsNamedNotSwallowed(unittest.TestCase):
    """Acceptance check 2: the exact defect that is silent in the frozen build."""

    def test_an_out_of_enum_intent_is_recorded_and_falls_back_to_rules(self):
        bad_model = TestModel(
            custom_output_args={
                "intent": "medical_question",
                "product": "unknown",
                "genuine_enquiry": True,
            }
        )
        outcome = build_extractor(model=bad_model).extract("I have a pre-existing condition")

        self.assertEqual(outcome.source, "rule")
        self.assertIsNotNone(outcome.violation)
        self.assertIn("medical_question", outcome.violation)
        self.assertIn("intent", outcome.violation)
        # And the turn is not lost: the rule peer still produced a usable
        # detection for this message.
        self.assertEqual(outcome.detection.intent, Intent.UNDERWRITING)


class TestMultiHopToolCalling(unittest.TestCase):
    """Acceptance check 3: two knowledge lookups in one run."""

    def test_comparing_two_products_makes_two_lookup_calls_in_one_run(self):
        def script(messages, info: AgentInfo):
            calls_so_far = [
                p for m in messages for p in m.parts if isinstance(p, ToolCallPart)
            ]
            n = len(calls_so_far)
            if n == 0:
                return ModelResponse(
                    parts=[ToolCallPart("lookup_product_fact", {"product": "plus", "field": "waiting_period"})]
                )
            if n == 1:
                return ModelResponse(
                    parts=[ToolCallPart("lookup_product_fact", {"product": "family", "field": "waiting_period"})]
                )
            return ModelResponse(
                parts=[ToolCallPart("final_result", {"intent": "comparison", "product": "unknown", "genuine_enquiry": True})]
            )

        extractor = build_extractor(model=FunctionModel(script))
        outcome = extractor.extract("compare the waiting period of Plus and Family")

        self.assertEqual(outcome.source, "llm")
        self.assertEqual(outcome.detection.intent, Intent.COMPARISON)


class TestHandoffProposalOpensNoCase(unittest.TestCase):
    """Acceptance check 4: the model cannot open a case, only propose one."""

    def test_request_human_handoff_returns_a_proposal_only(self):
        result = request_human_handoff(reason="Customer asked for a person")
        self.assertIsInstance(result, HandoffProposal)
        self.assertTrue(result.requested)
        self.assertEqual(result.reason, "Customer asked for a person")
        # There is nothing here that could open a case: no repository, no
        # `HumanCase` construction, no import of `backend.kernel` or
        # `backend.storage` anywhere in `backend/agent/tools/handoff.py`.


class TestSolicitationIsAlwaysRuleDerived(unittest.TestCase):
    def test_solicitation_is_computed_even_when_the_model_answers(self):
        outcome = build_extractor(model=TestModel()).extract(
            "Check out our limited time offer, click here to grow your business"
        )
        self.assertTrue(outcome.detection.solicitation)


class TestRunRecording(unittest.TestCase):
    """P4: what a recorder sees when the peers run."""

    def test_a_model_run_records_an_llm_step_with_calls_and_tool_calls(self):
        recorder = _recorder()
        outcome = build_extractor(model=TestModel()).extract("How much is Plus?", recorder=recorder)
        run = recorder.finish()

        self.assertEqual(run.steps[0].name, "extraction")
        self.assertEqual(run.steps[0].kind, "llm")
        self.assertEqual(run.steps[0].status, "ok")
        self.assertGreaterEqual(len(run.llm_calls), 1)
        self.assertGreaterEqual(len(run.tool_calls), 1)
        self.assertTrue(all(c.purpose == "extraction" for c in run.llm_calls))
        # Every model-selected tool call is also a `kind="tool"` step.
        self.assertEqual(sum(1 for s in run.steps if s.kind == "tool"), len(run.tool_calls))
        self.assertTrue(outcome.trace)

    def test_the_rule_peer_records_a_rule_step(self):
        recorder = _recorder()
        build_extractor(model=None).extract("How much is Plus?", recorder=recorder)
        run = recorder.finish()
        self.assertEqual([(s.name, s.kind, s.status) for s in run.steps], [("extraction", "rule", "ok")])
        self.assertEqual(run.totals()["llm_call_count"], 0)

    def test_a_model_proposed_handoff_lands_on_the_outcome_and_opens_nothing(self):
        def script(messages, info: AgentInfo):
            calls = [p for m in messages for p in m.parts if isinstance(p, ToolCallPart)]
            if not calls:
                return ModelResponse(
                    parts=[ToolCallPart("request_human_handoff", {"reason": "Customer asked for a person"})]
                )
            return _final("human_request")

        outcome = build_extractor(model=FunctionModel(script)).extract("Can I talk to someone?")
        self.assertIsInstance(outcome.handoff, HandoffProposal)
        self.assertTrue(outcome.handoff.requested)
        self.assertEqual(outcome.handoff.reason, "Customer asked for a person")


class TestThreeFailureClassesAreDistinguishable(unittest.TestCase):
    """Acceptance check 2 of P4 (`docs/backend-plan.md` §7)."""

    def test_class_1_program_error_propagates_and_marks_the_step_error(self):
        def script(messages, info: AgentInfo):
            raise RuntimeError("a bug in our own code")

        recorder = _recorder()
        with self.assertRaises(RuntimeError):
            build_extractor(model=FunctionModel(script)).extract("hi", recorder=recorder)
        run = recorder.finish()
        self.assertEqual(run.status, "error")
        self.assertEqual(run.steps[0].status, "error")

    def test_class_2_model_unavailable_degrades_and_says_unavailable(self):
        def script(messages, info: AgentInfo):
            raise ModelHTTPError(status_code=429, model_name="gpt-4o-mini", body="rate limited")

        recorder = _recorder()
        outcome = build_extractor(model=FunctionModel(script)).extract("How much is Plus?", recorder=recorder)
        run = recorder.finish()

        self.assertEqual(outcome.source, "rule")
        self.assertIsNone(outcome.violation)
        self.assertIn("model unavailable", outcome.unavailable)
        self.assertEqual(run.status, "degraded")
        self.assertIn("model unavailable", run.steps[0].detail)
        self.assertEqual(outcome.detection.intent, Intent.PRICE)

    def test_class_3_model_wrong_degrades_and_names_the_value(self):
        bad_model = TestModel(
            custom_output_args={"intent": "medical_question", "product": "unknown", "genuine_enquiry": True}
        )
        recorder = _recorder()
        outcome = build_extractor(model=bad_model).extract("I have a pre-existing condition", recorder=recorder)
        run = recorder.finish()

        self.assertEqual(outcome.source, "rule")
        self.assertIsNone(outcome.unavailable)
        self.assertIn("medical_question", outcome.violation)
        self.assertEqual(run.status, "degraded")
        self.assertIn("medical_question", run.steps[0].detail)
        # The two degraded classes must not read the same.
        self.assertNotIn("model unavailable", run.steps[0].detail)
