# -*- coding: utf-8 -*-
"""P5: the orchestrator — one customer message, end to end.

Acceptance criteria from `docs/backend-plan.md` §9 P5, restated:

    1. The five P0-5 idempotency criteria hold.
    3. Agent runs are queryable by `opportunity_id` and by
       `client_message_id`, with more than one run retained per conversation.

And the P0-1..P0-4 behaviours the frozen build paid for, walked end to end
rather than only at the kernel:

    P0-1  a price concern is hesitation, not a negotiation — no escalation
    P0-2  a competitor mention alone does not escalate
    P0-3  takeover persists, freezes the customer-facing state, never a second case
    P0-4  a discount request escalates *as a negotiation*
"""
from __future__ import annotations

import unittest

from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel

from backend import config
from backend.agent.extraction import build_extractor
from backend.agent.reply import build_composer
from backend.domain.enums import CaseStatus, Generation, OpportunityState, Qualification, Signal
from backend.kernel import hitl
from backend.services import cases
from backend.services.conversation import ConversationService
from backend.storage import MemoryRepository


def _service(model=None) -> ConversationService:
    return ConversationService(
        MemoryRepository(), extractor=build_extractor(model), composer=build_composer(model)
    )


class _Quiet(unittest.TestCase):
    """Keep the console renderer out of the test output."""

    def setUp(self):
        self._trace = config.CONSOLE_TRACE
        config.CONSOLE_TRACE = False

    def tearDown(self):
        config.CONSOLE_TRACE = self._trace


class TestIdempotency(_Quiet):
    """Acceptance 1: the five P0-5 criteria."""

    def setUp(self):
        super().setUp()
        self.svc = _service()
        self.first = self.svc.handle_customer_message("C-1", "Sarah", "How much is Plus?", client_message_id="k1")
        self.replay = self.svc.handle_customer_message("C-1", "Sarah", "How much is Plus?", client_message_id="k1")

    def test_1_replay_returns_the_stored_receipt_verbatim(self):
        self.assertTrue(self.replay.replayed)
        self.assertEqual(self.replay.receipt, self.first.receipt)
        self.assertEqual(self.replay.reply.text, self.first.reply.text)

    def test_2_counters_and_transcript_are_unchanged(self):
        opp = self.svc.repo.get_opportunity("C-1")
        self.assertEqual(opp.customer_message_count, 1)
        self.assertEqual(len(opp.messages), 2)

    def test_3_a_different_key_with_the_same_text_advances(self):
        self.svc.handle_customer_message("C-1", "Sarah", "How much is Plus?", client_message_id="k2")
        self.assertEqual(self.svc.repo.get_opportunity("C-1").customer_message_count, 2)

    def test_4_omitting_the_key_is_non_idempotent(self):
        self.svc.handle_customer_message("C-1", "Sarah", "How much is Plus?")
        self.svc.handle_customer_message("C-1", "Sarah", "How much is Plus?")
        self.assertEqual(self.svc.repo.get_opportunity("C-1").customer_message_count, 3)

    def test_5_no_new_score_history_entry_on_replay(self):
        self.assertEqual(len(self.svc.repo.get_opportunity("C-1").score_history), 1)

    def test_a_blank_customer_id_never_matches_a_receipt(self):
        a = self.svc.handle_customer_message("", "Anon", "Hello", client_message_id="k9")
        b = self.svc.handle_customer_message("", "Anon", "Hello", client_message_id="k9")
        self.assertFalse(b.replayed)
        self.assertNotEqual(a.opportunity.id, b.opportunity.id)


class TestRunsArePersistedPerMessage(_Quiet):
    """Acceptance 3."""

    def test_runs_queryable_by_both_keys_with_history_retained(self):
        svc = _service()
        svc.handle_customer_message("C-1", "Sarah", "Hi there", client_message_id="k1")
        svc.handle_customer_message("C-1", "Sarah", "How much is Plus?", client_message_id="k2")
        runs = svc.repo.list_runs(opportunity_id="C-1")
        self.assertEqual(len(runs), 2)
        self.assertEqual(svc.repo.list_runs(client_message_id="k2")[0]["run_id"], runs[0]["run_id"])
        self.assertEqual(runs[0]["customer_message_count"], 2)
        self.assertEqual([s["name"] for s in runs[0]["steps"]][:3], ["extraction", "takeover", "qualification"])

    def test_offline_turn_is_template_generated_and_the_run_is_degraded(self):
        """P7 acceptance 1 / `interface-v1.md` §5.7: with no model configured,
        every business message is `template` and the run reports `degraded`."""
        result = _service().handle_customer_message("C-1", "Sarah", "How much is Plus?")
        self.assertEqual(result.reply.generation, Generation.TEMPLATE)
        self.assertEqual(result.run.totals()["llm_call_count"], 0)
        self.assertEqual(result.run.status, "degraded")
        self.assertTrue(all(m.generation_value for m in result.opportunity.messages if not m.is_from_customer))

    def test_model_turn_is_llm_generated_and_continues_the_extraction_trace(self):
        # The default TestModel calls every tool once, including the handover
        # proposal, which would (correctly) escalate; restrict extraction to a
        # lookup. The reply agent has no tools, so it gets a plain TestModel.
        svc = ConversationService(
            MemoryRepository(),
            extractor=build_extractor(TestModel(call_tools=["lookup_product_fact"])),
            composer=build_composer(TestModel()),
        )
        result = svc.handle_customer_message("C-1", "Sarah", "How much is Plus?")
        self.assertEqual(result.reply.generation, Generation.LLM)
        purposes = [c["purpose"] for c in result.run.to_dict(include_content=False)["llm_calls"]]
        self.assertIn("extraction", purposes)
        self.assertIn("response_generation", purposes)
        self.assertEqual(result.extraction_source, "llm")


class TestTheFourFixesWalkEndToEnd(_Quiet):
    def test_p0_1_a_price_concern_is_hesitation_not_negotiation(self):
        svc = _service()
        svc.handle_customer_message("C-1", "Sarah", "How much does CareSure Plus cost?")
        result = svc.handle_customer_message("C-1", "Sarah", "Hmm, that's quite expensive for me.")
        self.assertIn(Signal.HESITATION, result.detection.signals)
        self.assertNotIn(Signal.NEGOTIATION, result.detection.signals)
        self.assertIsNone(result.case)
        self.assertFalse(result.opportunity.human_takeover)

    def test_p0_2_a_competitor_mention_alone_does_not_escalate(self):
        svc = _service()
        svc.handle_customer_message("C-1", "Sarah", "How much does CareSure Plus cost?")
        result = svc.handle_customer_message("C-1", "Sarah", "Another insurer offered something cheaper.")
        self.assertIn(Signal.COMPETITIVE, result.detection.signals)
        self.assertIsNone(result.case)

    def test_p0_4_a_discount_request_escalates_as_a_negotiation(self):
        svc = _service()
        svc.handle_customer_message("C-1", "Sarah", "How much does CareSure Plus cost?")
        result = svc.handle_customer_message("C-1", "Sarah", "Can you give me a discount?")
        self.assertIsNotNone(result.case)
        self.assertEqual(result.case.reason, hitl.REASON_NEGOTIATION)
        self.assertNotIn("medical", result.case.reason.lower())
        self.assertTrue(result.opportunity.human_takeover)
        self.assertEqual(result.reply.generation, Generation.TEMPLATE)
        self.assertEqual(result.quick_replies, [])

    def test_p0_3_takeover_persists_freezes_state_and_never_opens_a_second_case(self):
        svc = _service()
        svc.handle_customer_message("C-1", "Sarah", "How much does CareSure Plus cost?")
        escalated = svc.handle_customer_message("C-1", "Sarah", "Can you give me a discount?")
        frozen_state = escalated.opportunity.state

        later = svc.handle_customer_message("C-1", "Sarah", "How do I apply? I want to buy the plan.")
        self.assertTrue(later.opportunity.human_takeover)
        self.assertEqual(later.opportunity.state, frozen_state)
        self.assertEqual(len(svc.repo.list_cases()), 1)
        step = next(s for s in later.run.steps if s.name == "state_transition")
        self.assertIn("frozen", step.detail)
        self.assertTrue(later.next_best_action.human_intervention_required)

    def test_withdrawal_passes_through_the_freeze(self):
        svc = _service()
        svc.handle_customer_message("C-1", "Sarah", "How much does CareSure Plus cost?")
        svc.handle_customer_message("C-1", "Sarah", "Can you give me a discount?")
        result = svc.handle_customer_message("C-1", "Sarah", "Never mind, I'm not interested anymore.")
        self.assertEqual(result.opportunity.state, OpportunityState.DORMANT_LOST)
        self.assertEqual(result.opportunity.signals, [Signal.WITHDRAWAL])
        self.assertTrue(result.opportunity.human_takeover)

    def test_closing_the_case_hands_the_conversation_back(self):
        svc = _service()
        svc.handle_customer_message("C-1", "Sarah", "How much does CareSure Plus cost?")
        escalated = svc.handle_customer_message("C-1", "Sarah", "Can you give me a discount?")
        cases.set_status(svc.repo, escalated.case.id, CaseStatus.CLOSED)
        result = svc.handle_customer_message("C-1", "Sarah", "What does Plus cover?")
        self.assertFalse(result.opportunity.human_takeover)
        self.assertFalse(result.reply.text.startswith("Thanks for your message. A CareSure representative"))


class TestQualificationAndProposalOnTheRecord(_Quiet):
    def test_the_hold_reason_is_on_the_run_record(self):
        svc = _service()
        spam = "Check out our limited time offer, click here to grow your business"
        svc.handle_customer_message("C-9", "Bot", spam)
        result = svc.handle_customer_message("C-9", "Bot", spam)
        self.assertEqual(result.opportunity.qualification, Qualification.HELD)
        step = next(s for s in result.run.steps if s.name == "qualification")
        self.assertEqual(step.detail, result.opportunity.qualification_reason)
        self.assertEqual(result.quick_replies, [])

    def test_a_model_proposed_handover_is_recorded_and_honoured_through_the_gates(self):
        def script(messages, info: AgentInfo):
            calls = [p for m in messages for p in m.parts if isinstance(p, ToolCallPart)]
            if not calls:
                return ModelResponse(parts=[ToolCallPart("request_human_handoff", {"reason": "customer is upset"})])
            return ModelResponse(parts=[ToolCallPart(
                "final_result", {"intent": "coverage", "product": "plus", "genuine_enquiry": True}
            )])

        svc = ConversationService(
            MemoryRepository(), extractor=build_extractor(FunctionModel(script)), composer=build_composer(None)
        )
        result = svc.handle_customer_message("C-1", "Sarah", "What does Plus cover?")
        self.assertIsNotNone(result.case)
        self.assertTrue(result.case.reason.startswith(hitl.REASON_ASSISTANT_PROPOSED))
        step = next(s for s in result.run.steps if s.name == "hitl")
        self.assertIn("proposal='customer is upset' -> accepted", step.detail)
