# -*- coding: utf-8 -*-
"""P3: reply composition and the customer-visibility boundary.

Acceptance criteria from `docs/backend-plan.md` §9:

    5. Red line 3: the customer-reply prompt contains no internal state name,
       no signal name, no score and no priority band. Asserted against the
       assembled prompt text, not reviewed by eye.

Also covers the `MAX_HISTORY_MESSAGES` bound from §12.3: "`W` is not merely a
constant but a tested invariant. The assembled prompt must have an upper
bound regardless of transcript length."
"""
from __future__ import annotations

import unittest

from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel

from backend.agent import policy
from backend.agent.reply import ModelComposer, TemplateComposer, build_composer
from backend.agent.reply.model_based import _build_user_prompt
from backend.domain.detection import RetrievalResult
from backend.domain.enums import Generation, MessageAuthor, MessageRole, Product
from backend.domain.message import Message
from backend.observability import RunRecorder


def _retrieval(with_premium: bool = False) -> RetrievalResult:
    facts = ["CareSure Plus: solid mid-tier cover."]
    if with_premium:
        facts.append("Indicative premium: From S$1,000/year.")
    return RetrievalResult(facts=facts, confidence=0.9, product=Product.PLUS)


class TestOfflinePeer(unittest.TestCase):
    def test_build_composer_with_no_model_selects_the_template_peer(self):
        self.assertIsInstance(build_composer(model=None), TemplateComposer)

    def test_template_reply_is_marked_generation_template(self):
        composer = build_composer(model=None)
        message = composer.compose("Answer using approved facts.", _retrieval())
        self.assertEqual(message.role, MessageRole.BUSINESS)
        self.assertEqual(message.author, MessageAuthor.AI)
        self.assertEqual(message.generation, Generation.TEMPLATE)

    def test_template_reply_carries_the_disclaimer_when_a_premium_is_shown(self):
        composer = build_composer(model=None)
        message = composer.compose("Answer using approved facts.", _retrieval(with_premium=True))
        from backend import config

        self.assertIn(config.DEMO_DISCLAIMER, message.text)


class TestModelPeer(unittest.TestCase):
    def test_build_composer_with_a_model_selects_the_model_peer(self):
        self.assertIsInstance(build_composer(model=TestModel()), ModelComposer)

    def test_model_reply_is_marked_generation_llm(self):
        composer = build_composer(model=TestModel())
        message = composer.compose("Answer using approved facts.", _retrieval())
        self.assertEqual(message.generation, Generation.LLM)

    def test_withdrawal_and_takeover_never_go_through_the_model(self):
        """The one part of the frozen build's design this rebuild keeps: escalation
        and withdrawal replies are deterministic regardless of provider."""
        composer = build_composer(model=TestModel())
        withdrawal_msg = composer.compose("...", _retrieval(), withdrawal=True)
        takeover_msg = composer.compose("...", _retrieval(), takeover=True)
        self.assertEqual(withdrawal_msg.generation, Generation.TEMPLATE)
        self.assertEqual(takeover_msg.generation, Generation.TEMPLATE)


class TestRunRecording(unittest.TestCase):
    """P4: the composing step on the run record, and the unavailable fallback."""

    def _recorder(self) -> RunRecorder:
        return RunRecorder("C-1", content_enabled=True, content_max_chars=8000)

    def test_model_peer_records_an_llm_step_and_call(self):
        recorder = self._recorder()
        build_composer(model=TestModel()).compose("Answer using approved facts.", _retrieval(), recorder=recorder)
        run = recorder.finish()
        self.assertEqual((run.steps[0].name, run.steps[0].kind, run.steps[0].status), ("response_generation", "llm", "ok"))
        self.assertEqual(len(run.llm_calls), 1)
        self.assertEqual(run.llm_calls[0].purpose, "response_generation")

    def test_template_peer_records_a_rule_step(self):
        recorder = self._recorder()
        build_composer(model=None).compose("Answer using approved facts.", _retrieval(), recorder=recorder)
        run = recorder.finish()
        self.assertEqual((run.steps[0].name, run.steps[0].kind), ("response_generation", "rule"))
        self.assertEqual(run.totals()["llm_call_count"], 0)

    def test_model_unavailable_degrades_and_falls_back_to_a_template_reply(self):
        def script(messages, info: AgentInfo):
            raise ModelHTTPError(status_code=503, model_name="gpt-4o-mini", body="down")

        recorder = self._recorder()
        message = build_composer(model=FunctionModel(script)).compose(
            "Answer using approved facts.", _retrieval(), recorder=recorder
        )
        run = recorder.finish()
        self.assertEqual(message.generation, Generation.TEMPLATE)
        self.assertEqual(run.status, "degraded")
        self.assertIn("model unavailable", run.steps[0].detail)
        # The template fallback records its own rule step after the degraded llm step.
        self.assertEqual([s.kind for s in run.steps], ["llm", "rule"])


class TestRedLineThreeIsAssertedAgainstTheAssembledPrompt(unittest.TestCase):
    def test_a_clean_instruction_and_facts_pass(self):
        prompt = _build_user_prompt("Answer using approved facts.", _retrieval())
        policy.assert_customer_safe(prompt)  # must not raise

    def test_an_internal_state_name_in_the_instruction_is_caught(self):
        leaked = "The customer is in state Evaluation & Hesitation; answer helpfully."
        with self.assertRaises(ValueError):
            policy.assert_customer_safe(leaked)

    def test_a_signal_name_in_the_instruction_is_caught(self):
        leaked = "Competitive signal detected — steer them back to CareSure."
        with self.assertRaises(ValueError):
            policy.assert_customer_safe(leaked)

    def test_a_priority_band_in_the_instruction_is_caught(self):
        leaked = "This is a HIGH priority opportunity, close it."
        with self.assertRaises(ValueError):
            policy.assert_customer_safe(leaked)

    def test_the_actual_projection_function_never_produces_unsafe_text(self):
        for kwargs in (
            {"escalate": True},
            {"withdrawal": True},
            {"takeover": True},
            {"hesitation": True},
            {"high_intent": True},
            {},
        ):
            instruction = policy.customer_safe_projection(**kwargs)
            policy.assert_customer_safe(instruction)  # must not raise for any branch


class TestPromptHasAFixedUpperBound(unittest.TestCase):
    """§12.3: `W` is a tested invariant, not merely a constant."""

    def test_trim_history_caps_regardless_of_transcript_length(self):
        long_history = [
            Message.from_customer(f"message number {i}") for i in range(500)
        ]
        trimmed = policy.trim_history(long_history)
        self.assertLessEqual(len(trimmed), policy.MAX_HISTORY_MESSAGES)

    def test_trim_history_keeps_the_most_recent_messages(self):
        history = [Message.from_customer(f"m{i}") for i in range(10)]
        trimmed = policy.trim_history(history)
        self.assertEqual(trimmed[-1].text, "m9")
