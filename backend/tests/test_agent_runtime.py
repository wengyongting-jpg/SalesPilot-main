# -*- coding: utf-8 -*-
"""P3b: the two-segment agent loop, the reply peers, and the framework go/no-go.

The shape being asserted is the one settled in review and recorded in
`docs/backend-plan.md` §3:

    observing segment   the model leads, choosing read-only tools
    kernel              a mandatory, exactly-once step run by `services` — not here
    composing segment   the model leads again, continuing the SAME conversation

"Two segments" is not "two disconnected chats". They share one message history, so
the model that words the reply remembers how it reached its understanding and what it
looked up. Only a **customer-safe projection** of the kernel's verdict crosses into
that history; the full verdict goes to storage and telemetry directly.

Everything here runs with `TestModel`, so the whole loop including tool selection is
exercised with no key and no network. That property is also what makes the offline
mode a peer rather than a stub.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from backend.domain.decision import NextBestAction
from backend.domain.enums import (
    Generation,
    Intent,
    KnowledgeField,
    Priority,
    Product,
    ReplyMode,
)
from backend.domain.message import Message
from backend.domain.opportunity import Opportunity

NOW = datetime(2026, 9, 22, 12, 0)


def action(mode=ReplyMode.ANSWER, priority=Priority.MEDIUM) -> NextBestAction:
    return NextBestAction(
        action="Answer the question with grounded information",
        reason="internal reasoning a customer must never read",
        priority=priority,
        reply_mode=mode,
    )


def conversation(messages: int = 2) -> Opportunity:
    opp = Opportunity(id="C-R", customer_name="Sam", product=Product.PLUS)
    opp.customer_message_count = messages
    for index in range(messages):
        opp.messages.append(
            Message.from_customer(f"question {index}", ts=NOW - timedelta(minutes=index))
        )
        opp.messages.append(
            Message.from_ai(f"answer {index}", generation=Generation.LLM)
        )
    return opp


class TestTemplateComposer(unittest.TestCase):
    """The offline peer. A full conversation completes on this alone."""

    def _compose(self, mode, facts=None, **kwargs):
        from backend.agent.reply.template import TemplateComposer
        from backend.agent.reply import ReplyRequest

        return TemplateComposer().compose(
            ReplyRequest(
                facts=facts if facts is not None else ["CareSure Plus: private cover."],
                action=action(mode),
                customer_name="Sam",
                disclaimer="Demo disclaimer text.",
                **kwargs,
            )
        )

    def test_it_marks_itself_as_template_generated(self):
        """`generation` is what stops a template reply being mistaken for a model
        one. A reader must never be misled about that."""
        outcome = self._compose(ReplyMode.ANSWER)
        self.assertIs(Generation.TEMPLATE, outcome.generation)
        self.assertTrue(outcome.text.strip())

    def test_it_answers_from_the_supplied_facts_only(self):
        outcome = self._compose(
            ReplyMode.ANSWER, facts=["Indicative premium: From S$1,500/year."]
        )
        self.assertIn("S$1,500", outcome.text)

    def test_a_premium_figure_always_carries_the_disclaimer(self):
        """A compliance red line: the disclaimer is never truncated or dropped."""
        outcome = self._compose(
            ReplyMode.ANSWER, facts=["Indicative premium: From S$1,500/year."]
        )
        self.assertIn("Demo disclaimer text.", outcome.text)

    def test_no_disclaimer_is_appended_when_no_premium_is_quoted(self):
        outcome = self._compose(ReplyMode.ANSWER, facts=["Coverage: private hospital."])
        self.assertNotIn("Demo disclaimer text.", outcome.text)

    def test_a_handover_reply_stops_selling(self):
        outcome = self._compose(ReplyMode.HANDOVER)
        lowered = outcome.text.lower()
        self.assertIn("representative", lowered)
        for pushy in ("great to hear", "apply now", "sign up", "let's get started"):
            self.assertNotIn(pushy, lowered)

    def test_a_withdrawal_reply_does_not_argue(self):
        outcome = self._compose(ReplyMode.WITHDRAWN)
        lowered = outcome.text.lower()
        for pushy in ("great to hear", "apply now", "interested", "would you like"):
            self.assertNotIn(pushy, lowered)

    def test_a_held_reply_describes_no_plan_and_quotes_no_figure(self):
        outcome = self._compose(
            ReplyMode.HOLD, facts=["Indicative premium: From S$1,500/year."]
        )
        self.assertNotIn("S$1,500", outcome.text)
        self.assertNotIn("Plus", outcome.text)

    def test_every_mode_produces_something_to_send(self):
        for mode in ReplyMode:
            with self.subTest(mode.value):
                self.assertTrue(self._compose(mode).text.strip())

    def test_it_never_leaks_the_internal_reasoning_it_was_given(self):
        outcome = self._compose(ReplyMode.CLOSE)
        self.assertNotIn("internal reasoning", outcome.text)
        self.assertNotIn("MEDIUM", outcome.text)


class TestOfflineRuntime(unittest.TestCase):
    """No provider configured: rules plus templates, end to end."""

    def _runtime(self):
        from backend.agent.runtime import AgentRuntime
        from backend.knowledge import loader

        return AgentRuntime(kb=loader.load(), model=None)

    def test_it_observes_without_a_model_and_says_so(self):
        outcome = self._runtime().observe("How much does CareSure Plus cost?")
        self.assertIs(Intent.PRICE, outcome.extraction.detection.intent)
        self.assertEqual("rules", outcome.extraction.source)
        self.assertTrue(outcome.extraction.degraded)
        self.assertIn("no model", (outcome.extraction.degradation_reason or "").lower())

    def test_it_composes_without_a_model_and_marks_the_generation(self):
        runtime = self._runtime()
        observation = runtime.observe("How much does CareSure Plus cost?")
        reply = runtime.compose(
            observation, action=action(ReplyMode.ANSWER), facts=["Premium: S$1,500."]
        )
        self.assertIs(Generation.TEMPLATE, reply.generation)
        self.assertTrue(reply.degraded)

    def test_no_tool_calls_are_claimed_when_no_model_ran(self):
        """`interface-v1.md` §1.1 rule 2: a tool call means one the model chose.
        Fixed retrieval is not one, and inventing a count to fill a dashboard would
        manufacture the defect that rule exists to prevent."""
        observation = self._runtime().observe("How much is Plus?")
        self.assertEqual(0, observation.tool_calls)


class TestModelBackedRuntime(unittest.TestCase):
    """The same loop against `TestModel`: real framework, no network."""

    def _runtime(self, **kwargs):
        from pydantic_ai.models.test import TestModel

        from backend.agent.runtime import AgentRuntime
        from backend.knowledge import loader

        # TestModel deliberately calls every registered tool. Production is capped
        # at three; this fixture uses seven so one synthetic run can exercise all
        # registered adapters
        # adapters without turning the limit test into every runtime test.
        return AgentRuntime(
            kb=loader.load(), model=TestModel(call_tools="all"),
            max_tool_calls=7, **kwargs
        )

    def test_a_run_completes_offline_and_selects_at_least_one_tool(self):
        """The acceptance check for P3: a genuine tool-calling loop exists."""
        observation = self._runtime().observe(
            "What is the waiting period for CareSure Plus?"
        )
        self.assertEqual("llm", observation.extraction.source)
        self.assertGreaterEqual(observation.tool_calls, 1)
        self.assertIsNotNone(observation.extraction.detection)

    def test_a_bad_tool_argument_is_recorded_and_does_not_abort_the_run(self):
        """`TestModel` supplies synthetic arguments, which is useful here: it fuzzes
        the tool surface for free.

        The first version of the wrappers called `Product(value)` directly, so one
        hallucinated argument raised out of the tool and degraded the entire
        extraction to the rule-based peer. A real provider will occasionally invent an
        argument, and losing a whole pipeline run to it is not acceptable. The tool now
        reports the permitted values back to the model and records a violation.
        """
        observation = self._runtime().observe("Tell me about the waiting period")
        self.assertEqual("llm", observation.extraction.source)
        self.assertTrue(observation.extraction.violations)
        offending = observation.extraction.violations[0]
        self.assertIn(offending.field, {"product", "field", "products"})
        self.assertTrue(offending.allowed)
        # Reported, not hidden.
        self.assertTrue(observation.extraction.degraded)
        self.assertIn("not a permitted value", observation.extraction.degradation_reason)

    def test_the_tool_calls_are_recorded_by_name_for_the_timeline(self):
        runtime = self._runtime()
        observation = runtime.observe("Compare the waiting period of Plus and Family")
        names = [call.name for call in observation.tool_context.calls]
        self.assertTrue(names)
        for name in names:
            self.assertIn(
                name,
                {
                    "lookup_product_fact", "compare_products", "list_products",
                    "conversation_summary", "request_human_handoff",
                    "get_staff_availability", "propose_customer_question",
                },
            )

    def test_named_plan_comparison_exposes_only_focused_tools(self):
        observation = self._runtime().observe(
            "Compare Essential, Family and Plus for me."
        )
        names = {
            part.tool_name for message in observation.history for part in message.parts
            if hasattr(part, "tool_name")
        }
        self.assertIn("compare_products", names)
        self.assertNotIn("list_products", names)
        self.assertNotIn("conversation_summary", names)

    def test_a_handoff_request_proposes_and_opens_nothing(self):
        runtime = self._runtime()
        observation = runtime.observe("I want to speak to a human")
        proposal = observation.tool_context.handoff
        # TestModel exercises every tool, so the proposal is recorded; what matters
        # is that recording it is all that happened.
        self.assertTrue(proposal.requested)
        self.assertIsNone(getattr(proposal, "case", None))

    def test_the_composing_segment_continues_the_same_conversation(self):
        """Not two disconnected chats: the customer's turn and the tool round trips
        carry over, so the model wording the reply remembers what it looked up."""
        from backend.agent.runtime import continuity_history

        runtime = self._runtime()
        observation = runtime.observe("How much is Plus?")
        carried = continuity_history(observation.history)
        self.assertTrue(carried, "nothing carried over — the segments are disconnected")

        reply = runtime.compose(
            observation, action=action(ReplyMode.ANSWER), facts=["Premium: S$1,500."]
        )
        self.assertGreater(len(reply.history), len(carried))

        text = self._flatten(reply.history)
        self.assertIn("How much is Plus?", text, "the customer's own turn was lost")
        self.assertIn(
            "Premium: S$1,500.", text,
            "the approved fact did not cross in the safe reply data block",
        )

    def test_what_carries_over_excludes_the_internal_taxonomy(self):
        """The counterpart of the test above, and the correction to a first version
        that shared the history verbatim.

        The extraction system prompt has to list every signal and intent, because the
        extractor must be told what it may report. Leaving that in context while the
        model writes to a customer puts the taxonomy one echo away from them. So it is
        dropped, along with the labels the model assigned.
        """
        from backend.agent.runtime import continuity_history
        from pydantic_ai.messages import SystemPromptPart

        runtime = self._runtime()
        carried = continuity_history(runtime.observe("How much is Plus?").history)
        self.assertFalse(
            any(isinstance(part, SystemPromptPart)
                for message in carried for part in message.parts),
            "the extraction system prompt carried over",
        )
        text = self._flatten(carried)
        for signal in ("Purchase Preparation", "Compliance Risk", "Expansion: Family"):
            self.assertNotIn(signal, text)

    @staticmethod
    def _flatten(history) -> str:
        chunks = []
        for message in history:
            for part in message.parts:
                content = getattr(part, "content", None)
                if isinstance(content, str):
                    chunks.append(content)
                args = getattr(part, "args", None)
                if isinstance(args, str):
                    chunks.append(args)
        return "\n".join(chunks)

    def test_the_verdict_crosses_over_only_as_a_safe_projection(self):
        """Red line 3 at the point the verdict enters the model's context."""
        from backend.domain.enums import OpportunityState, Signal

        runtime = self._runtime()
        observation = runtime.observe("How much is Plus?")
        reply = runtime.compose(
            observation,
            action=NextBestAction(
                action="Contact the customer to close",
                reason="High purchase readiness - prioritise immediate sales contact",
                priority=Priority.HIGH,
                reply_mode=ReplyMode.CLOSE,
            ),
            facts=["Premium: S$1,500."],
        )
        injected = self._flatten(reply.history)
        for state in OpportunityState:
            self.assertNotIn(state.value, injected)
        for signal in Signal:
            self.assertNotIn(signal.value, injected)
        self.assertNotIn("prioritise immediate sales contact", injected)


class TestCostGuards(unittest.TestCase):
    """The three quadratic paths from `docs/backend-plan.md` §12.3."""

    def test_the_context_window_is_bounded_regardless_of_transcript_length(self):
        """The insidious one. An unbounded window is *cheaper* at ten turns and
        quadratic by three hundred, so no short test would ever reveal it."""
        from backend.agent import runtime as runtime_module

        long_conversation = conversation(messages=400)
        window = runtime_module.build_context(long_conversation.messages)
        self.assertLessEqual(len(window), runtime_module.CONTEXT_WINDOW)

    def test_the_window_keeps_the_most_recent_turns(self):
        from backend.agent import runtime as runtime_module

        opp = conversation(messages=10)
        window = runtime_module.build_context(opp.messages)
        self.assertEqual(opp.messages[-1].text, window[-1].text)

    def test_a_runaway_tool_loop_is_capped_by_the_framework(self):
        """At fifty tool calls one message costs 256,000 input tokens. The cap is
        enforced before a request is sent, so a runaway costs nothing."""
        from backend.agent.runtime import AgentRuntime

        limits = AgentRuntime.usage_limits(max_tool_calls=3)
        self.assertEqual(3, limits.tool_calls_limit)
        self.assertIsNotNone(limits.request_limit)
        self.assertIsNotNone(limits.total_tokens_limit)
        self.assertIsNotNone(limits.output_tokens_limit)
        self.assertIsNotNone(limits.per_request_input_tokens_limit)
        self.assertIsNotNone(limits.cost_limit)

    def test_a_tool_cap_breach_degrades_rather_than_failing_the_request(self):
        """A customer message must still receive an answer. Exceeding a budget is an
        operational event, not a reason to drop the conversation."""
        from pydantic_ai.models.test import TestModel

        from backend.agent.runtime import AgentRuntime
        from backend.knowledge import loader

        runtime = AgentRuntime(
            kb=loader.load(), model=TestModel(call_tools="all"), max_tool_calls=0
        )
        observation = runtime.observe("Compare everything about every plan")
        self.assertTrue(observation.extraction.degraded)
        self.assertIsNotNone(observation.extraction.detection)


if __name__ == "__main__":
    unittest.main()
