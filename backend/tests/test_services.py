# -*- coding: utf-8 -*-
"""P5b: the orchestrator, and the first time everything is wired together.

This is where the central design claim of the rebuild becomes true or false. The
kernel is supposed to be a **mandatory, exactly-once step executed by `services`** —
not a tool the model may skip, repeat or reorder (`docs/backend-plan.md` §3). Until
now that was an argument; here it is a line of Python, and these tests are what hold
it to account.

Also asserted end to end rather than per-unit:

    the five idempotency criteria of `backend-contract.md` Part B item 1
    the takeover freeze of P0-3
    the qualification gate of gap register item 13
    a complete conversation with no model configured at all
"""
from __future__ import annotations

import shutil
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from backend.domain.enums import (
    CaseStatus,
    Generation,
    MessageRole,
    OpportunityState,
    Priority,
    Product,
    Qualification,
    Signal,
)

NOW = datetime(2026, 9, 22, 12, 0, 0)


def service(repo=None, *, now=None, extractor=None, composer=None):
    from backend.agent.extraction import RuleExtractor
    from backend.agent.reply.template import TemplateComposer
    from backend.services.conversation import ConversationService
    from backend.storage.memory import InMemoryRepository

    moment = now or NOW
    return ConversationService(
        repo or InMemoryRepository(),
        extractor=extractor or RuleExtractor(offline=True),
        composer=composer or TemplateComposer(),
        now=lambda: moment
    )


def send(svc, text, *, customer_id="C-1", name="Sam", key=None):
    return svc.handle_customer_message(
        customer_id=customer_id, customer_name=name, text=text, client_message_id=key
    )


class TestTheKernelRunsExactlyOnce(unittest.TestCase):
    """The claim the architecture rests on."""

    def test_every_deterministic_step_runs_once_per_message(self):
        svc = service()
        result = send(svc, "How much does CareSure Plus cost?")
        names = [step["name"] for step in result.to_dict()["agent_run"]["steps"]]

        for expected in (
            "extraction", "takeover", "state_transition", "profile_update",
            "qualification", "scoring", "knowledge_retrieval", "hitl",
            "next_best_action", "response_generation",
        ):
            self.assertEqual(
                1, names.count(expected), f"{expected} ran {names.count(expected)} times"
            )

    def test_the_deterministic_steps_run_in_their_required_order(self):
        """These rules are order-dependent: transition first, score against the new
        state, band the score, derive the action from the band. Retrieval precedes
        HITL because the escalation rules read its confidence."""
        svc = service()
        names = [
            step["name"]
            for step in send(svc, "How much is Plus?").to_dict()["agent_run"]["steps"]
        ]
        for earlier, later in (
            ("extraction", "state_transition"),
            ("state_transition", "scoring"),
            ("scoring", "next_best_action"),
            ("knowledge_retrieval", "hitl"),
            ("hitl", "response_generation"),
        ):
            self.assertLess(
                names.index(earlier), names.index(later),
                f"{earlier} must run before {later}",
            )

    def test_the_kernel_runs_even_with_no_model_at_all(self):
        """In offline mode there is no agent loop for the kernel to live inside. This
        is the decisive reason it is not a tool."""
        # Offline mode: use rule-based extractor and template composer
        svc = service()
        result = send(svc, "How much is Plus?")
        self.assertIsNotNone(result.score)
        self.assertIsNotNone(result.next_best_action)
        self.assertIs(Product.PLUS, result.opportunity.product)


class TestIdempotency(unittest.TestCase):
    """`backend-contract.md` Part B item 1. Silent score inflation, not an exception."""

    def test_a_replayed_key_changes_nothing(self):
        svc = service()
        first = send(svc, "hello", key="k1")
        replay = send(svc, "hello", key="k1")

        self.assertFalse(first.replayed)
        self.assertTrue(replay.replayed)
        self.assertEqual(first.to_dict(), replay.to_dict())

    def test_the_message_count_and_transcript_do_not_advance(self):
        svc = service()
        send(svc, "hello", key="k1")
        send(svc, "hello", key="k1")
        opp = svc.repo.get_opportunity("C-1")
        self.assertEqual(1, opp.customer_message_count)
        self.assertEqual(2, len(opp.messages))

    def test_no_second_score_history_entry_is_written(self):
        svc = service()
        send(svc, "hello", key="k1")
        send(svc, "hello", key="k1")
        self.assertEqual(1, len(svc.repo.get_opportunity("C-1").score_history))

    def test_a_different_key_with_the_same_text_does_advance(self):
        svc = service()
        send(svc, "hello", key="k1")
        second = send(svc, "hello", key="k2")
        self.assertFalse(second.replayed)
        self.assertEqual(2, svc.repo.get_opportunity("C-1").customer_message_count)

    def test_omitting_the_key_preserves_the_original_behaviour(self):
        svc = service()
        send(svc, "hello")
        send(svc, "hello")
        self.assertEqual(2, svc.repo.get_opportunity("C-1").customer_message_count)

    def test_a_replay_records_no_second_agent_run(self):
        """A replay does no work, so claiming a run would inflate the cost totals."""
        svc = service()
        send(svc, "hello", key="k1")
        send(svc, "hello", key="k1")
        self.assertEqual(1, len(svc.repo.list_runs(opportunity_id="C-1")))

    def test_the_key_is_recorded_on_the_stored_message(self):
        svc = service()
        send(svc, "hello", key="k-echo")
        messages = svc.repo.get_opportunity("C-1").messages
        self.assertEqual("k-echo", messages[0].client_message_id)
        self.assertIsNone(messages[1].client_message_id)


class TestAgentRunPersistence(unittest.TestCase):
    def test_a_run_is_saved_for_every_message(self):
        svc = service()
        send(svc, "How much is Plus?")
        send(svc, "How do I apply?")
        self.assertEqual(2, len(svc.repo.list_runs(opportunity_id="C-1")))

    def test_a_run_is_queryable_by_the_client_message_id(self):
        svc = service()
        send(svc, "hello", key="c-8f2a")
        found = svc.repo.list_runs(opportunity_id="C-1", client_message_id="c-8f2a")
        self.assertEqual(1, len(found))

    def test_conversation_totals_accumulate(self):
        svc = service()
        send(svc, "How much is Plus?")
        send(svc, "And the waiting period?")
        totals = svc.repo.conversation_totals("C-1")
        self.assertEqual(2, totals["run_count"])

    def test_an_offline_run_is_recorded_as_degraded(self):
        svc = service()
        run = send(svc, "How much is Plus?").to_dict()["agent_run"]
        self.assertEqual("degraded", run["status"])
        self.assertEqual(0, run["totals"]["llm_call_count"])
        self.assertEqual(0, run["totals"]["tool_call_count"])


class TestOfflineConversation(unittest.TestCase):
    """A complete conversation with nothing configured."""

    def test_the_reply_is_marked_as_template_generated(self):
        svc = service()
        result = send(svc, "How much does CareSure Plus cost?")
        self.assertIs(Generation.TEMPLATE, result.reply.generation)
        self.assertIs(MessageRole.BUSINESS, result.reply.role)
        self.assertEqual("message(rules)", result.opportunity.score_history[-1].trigger)

    def test_a_premium_reply_carries_the_disclaimer(self):
        svc = service()
        result = send(svc, "How much does CareSure Plus cost?")
        self.assertIn("S$", result.reply.text)
        self.assertIn("fictional indicative", result.reply.text)

    def test_the_journey_advances_across_several_messages(self):
        svc = service()
        send(svc, "I want private hospital coverage")
        send(svc, "How much is the Plus plan?")
        final = send(svc, "Okay, how do I apply?")
        self.assertIs(OpportunityState.HIGH_INTENT, final.opportunity.state)
        self.assertIn(Signal.PURCHASE, final.opportunity.signals)


class TestTakeoverFreeze(unittest.TestCase):
    """P0-3, now through the whole pipeline rather than the kernel alone."""

    def _under_takeover(self):
        svc = service()
        send(svc, "I want to speak to a human agent")
        send(svc, "Confirm")
        opp = svc.repo.get_opportunity("C-1")
        self.assertTrue(opp.human_takeover, "setup failed: takeover not active")
        return svc, opp

    def test_takeover_persists_across_a_later_message(self):
        svc, _ = self._under_takeover()
        result = send(svc, "How much is Plus?")
        self.assertTrue(result.opportunity.human_takeover)
        self.assertTrue(result.next_best_action.human_intervention_required)

    def test_a_vague_message_does_not_move_the_state_or_drop_the_score(self):
        svc, before = self._under_takeover()
        result = send(svc, "ok")
        self.assertIs(before.state, result.opportunity.state)
        self.assertGreaterEqual(result.score.total, before.score.total)

    def test_no_second_case_is_opened(self):
        svc, _ = self._under_takeover()
        send(svc, "Also, can you give me a discount?")
        active = [c for c in svc.repo.list_cases() if c.status is not CaseStatus.CLOSED]
        self.assertEqual(1, len(active))

    def test_no_quick_replies_are_offered(self):
        svc, _ = self._under_takeover()
        self.assertEqual([], send(svc, "How much is Plus?").quick_replies)

    def test_the_customers_own_withdrawal_still_moves_the_opportunity(self):
        svc, _ = self._under_takeover()
        result = send(svc, "Actually I won't buy anymore.")
        self.assertIs(OpportunityState.DORMANT_LOST, result.opportunity.state)
        self.assertTrue(result.opportunity.human_takeover, "takeover must remain")


class TestQualificationGate(unittest.TestCase):
    """Gap register item 13, end to end."""

    def test_repeated_solicitation_is_held_and_leaves_the_queue(self):
        svc = service()
        send(svc, "We sell insurance leads, visit example.com")
        result = send(svc, "Buy our database, click here for a promo code")

        self.assertIs(Qualification.HELD, result.opportunity.qualification)
        self.assertFalse(result.opportunity.is_sellable)
        self.assertIs(Priority.LOW, result.score.priority)
        self.assertEqual([], result.quick_replies)

    def test_a_held_conversation_is_not_sold_to(self):
        svc = service()
        send(svc, "We sell insurance leads, visit example.com")
        result = send(svc, "Buy our list now, limited offer")
        self.assertNotIn("S$", result.reply.text)
        self.assertEqual([], result.to_dict()["customer_facts"])

    def test_a_handover_reply_arrives_without_product_cards(self):
        """The reply and the cards must agree. Returning a premium alongside "a
        representative will be in touch" would put a price card under a handover
        message — and would be the assistant still selling during the handover."""
        svc = service()
        send(svc, "How much is the Plus plan?")
        result = send(svc, "I want to speak to a human agent")
        self.assertEqual([], result.to_dict()["customer_facts"])
        self.assertTrue(result.retrieval.facts, "retrieval still ran")

    def test_a_genuine_customer_is_never_held(self):
        svc = service()
        for text in ("I want private hospital coverage",
                     "How much is the Plus plan?",
                     "Okay, how do I apply?"):
            result = send(svc, text)
        self.assertIs(Qualification.QUALIFIED, result.opportunity.qualification)

    def test_the_hold_reason_is_recorded_for_review(self):
        svc = service()
        send(svc, "We sell insurance leads, visit example.com")
        send(svc, "Buy our database now")
        opp = svc.repo.get_opportunity("C-1")
        self.assertTrue(opp.qualification_reason)


class TestEscalation(unittest.TestCase):
    def test_a_negotiation_opens_a_case_with_an_accurate_reason(self):
        """P0-4. The reason decides how a representative prepares."""
        svc = service()
        send(svc, "How much is the Plus plan?")
        result = send(svc, "Can you give me a discount?")
        self.assertIsNone(result.case)
        result = send(svc, "Confirm")

        self.assertIsNotNone(result.case)
        self.assertIn("negotiation", result.case.reason.lower())
        for wrong in ("medical", "underwriting", "compliance"):
            self.assertNotIn(wrong, result.case.reason.lower())

    def test_a_price_concern_opens_nothing(self):
        svc = service()
        send(svc, "How much is the Plus plan?")
        result = send(svc, "That seems a little expensive.")
        self.assertIsNone(result.case)
        self.assertEqual([], svc.repo.list_cases())

    def test_the_case_is_persisted_and_findable(self):
        svc = service()
        send(svc, "I want to speak to a human agent")
        send(svc, "Confirm")
        self.assertIsNotNone(svc.repo.active_case_for("C-1"))


class TestRepReply(unittest.TestCase):
    """`interface-v1.md` §5.4."""

    def _service_under_takeover(self):
        svc = service()
        send(svc, "I want to speak to a human agent")
        send(svc, "Confirm")
        return svc

    def test_it_is_refused_when_nobody_has_taken_over(self):
        from backend.services.rep_reply import NotUnderTakeover, RepReplyService

        svc = service()
        send(svc, "How much is Plus?")
        rep = RepReplyService(svc.repo)
        with self.assertRaises(NotUnderTakeover):
            rep.reply("C-1", text="Hello", rep_name="Alex")

    def test_a_refusal_appends_nothing(self):
        from backend.services.rep_reply import NotUnderTakeover, RepReplyService

        svc = service()
        send(svc, "How much is Plus?")
        before = len(svc.repo.get_opportunity("C-1").messages)
        try:
            RepReplyService(svc.repo).reply("C-1", text="Hi", rep_name="Alex")
        except NotUnderTakeover:
            pass
        self.assertEqual(before, len(svc.repo.get_opportunity("C-1").messages))

    def test_under_takeover_it_appends_a_human_attributed_message(self):
        from backend.services.rep_reply import RepReplyService

        svc = self._service_under_takeover()
        message = RepReplyService(svc.repo).reply(
            "C-1", text="Alex here, happy to help.", rep_name="Alex"
        )
        self.assertIs(MessageRole.BUSINESS, message.role)
        self.assertEqual("human", message.author_value)
        self.assertEqual("human", message.generation_value)
        self.assertEqual("Alex", message.rep_name)

    def test_it_runs_none_of_the_pipeline(self):
        """No detection, no scoring, no transition, no HITL — the human is talking."""
        from backend.services.rep_reply import RepReplyService

        svc = self._service_under_takeover()
        before = svc.repo.get_opportunity("C-1")
        # `InMemoryRepository.get_opportunity` returns the live object, not a
        # copy, so `before` and the `after` fetched below are the same
        # instance — anything read from `before` *after* the reply call
        # already reflects it. The scalar fields are unaffected by a rep
        # reply either way (that is what this test asserts), but the message
        # count must be captured before the mutation to mean anything.
        before_message_count = len(before.messages)
        before_customer_message_count = before.customer_message_count
        before_state = before.state
        before_score_total = before.score.total
        before_signals = list(before.signals)
        before_score_history_len = len(before.score_history)

        RepReplyService(svc.repo).reply("C-1", text="Anything at all", rep_name="Alex")
        after = svc.repo.get_opportunity("C-1")

        self.assertEqual(before_customer_message_count, after.customer_message_count)
        self.assertIs(before_state, after.state)
        self.assertEqual(before_score_total, after.score.total)
        self.assertEqual(before_signals, after.signals)
        self.assertEqual(before_score_history_len, len(after.score_history))
        self.assertEqual(before_message_count + 1, len(after.messages))

    def test_an_unknown_conversation_is_reported_as_missing(self):
        from backend.services.rep_reply import RepReplyService, UnknownOpportunity

        svc = service()
        with self.assertRaises(UnknownOpportunity):
            RepReplyService(svc.repo).reply("C-nope", text="Hi", rep_name="Alex")

    def test_a_replayed_key_does_not_duplicate_the_reply(self):
        from backend.services.rep_reply import RepReplyService

        svc = self._service_under_takeover()
        rep = RepReplyService(svc.repo)
        rep.reply("C-1", text="Hi", rep_name="Alex", client_message_id="r-1")
        rep.reply("C-1", text="Hi", rep_name="Alex", client_message_id="r-1")
        human = [
            m for m in svc.repo.get_opportunity("C-1").messages
            if m.author_value == "human"
        ]
        self.assertEqual(1, len(human))


class TestCaseService(unittest.TestCase):
    @staticmethod
    def _confirmed_service():
        svc = service()
        send(svc, "I want to speak to a human agent")
        send(svc, "Confirm")
        return svc

    def test_closing_a_case_resumes_autonomous_selling(self):
        """The admin console tells a representative this will happen. If it stopped
        being true the warning would become a lie."""
        from backend.services.cases import CaseService

        svc = self._confirmed_service()
        case = svc.repo.active_case_for("C-1")

        updated = CaseService(svc.repo).transition(case.id, CaseStatus.CLOSED)
        self.assertIs(CaseStatus.CLOSED, updated.status)
        opp = svc.repo.get_opportunity("C-1")
        self.assertFalse(opp.human_takeover)
        self.assertFalse(opp.human_intervention_required)

    def test_taking_over_sets_the_flag(self):
        """Gap register item 14, criterion 1.

        This assertion used to pass for the wrong reason: escalation had already set the
        flag, so the transition could do nothing at all and the test stayed green. The
        round-trip below is the one that can fail.
        """
        from backend.services.cases import CaseService

        svc = self._confirmed_service()
        case = svc.repo.active_case_for("C-1")
        CaseService(svc.repo).transition(case.id, CaseStatus.TAKEN_OVER)
        self.assertTrue(svc.repo.get_opportunity("C-1").human_takeover)

    def test_a_case_can_be_taken_over_closed_and_taken_over_again(self):
        """Item 14, criterion 5, and where the defect actually lived.

        Closing resumes autonomy, so a second takeover has to set the flag itself with
        no escalation to help it. Until it did, the console PATCHed a case to
        `Taken Over`, saw it succeed, and then had its rep reply refused with "take over
        first" - said to the operator who had just done exactly that.
        """
        from backend.services.cases import CaseService

        svc = self._confirmed_service()
        cases = CaseService(svc.repo)
        case = svc.repo.active_case_for("C-1")

        cases.transition(case.id, CaseStatus.CLOSED)
        self.assertFalse(
            svc.repo.get_opportunity("C-1").human_takeover,
            "closing must resume autonomy",
        )

        cases.transition(case.id, CaseStatus.TAKEN_OVER)
        self.assertTrue(
            svc.repo.get_opportunity("C-1").human_takeover,
            "a second takeover must set the flag with no escalation in between",
        )

    def test_reopening_a_case_leaves_the_flags_alone(self):
        """Item 14, criterion 4. An open case means the assistant is still handling the
        conversation and nobody has claimed it, so reopening must claim nothing."""
        from backend.services.cases import CaseService

        svc = self._confirmed_service()
        cases = CaseService(svc.repo)
        case = svc.repo.active_case_for("C-1")

        cases.transition(case.id, CaseStatus.CLOSED)
        cases.transition(case.id, CaseStatus.OPEN)

        opp = svc.repo.get_opportunity("C-1")
        self.assertFalse(opp.human_takeover)
        self.assertFalse(opp.human_intervention_required)

    def test_taking_over_preserves_the_reason_a_person_was_needed(self):
        """`human_intervention_required` records that a person was *needed*, which
        taking the case over does not change. Clearing it would lose why it opened."""
        from backend.services.cases import CaseService

        svc = self._confirmed_service()
        case = svc.repo.active_case_for("C-1")
        before = svc.repo.get_opportunity("C-1").human_intervention_required

        CaseService(svc.repo).transition(case.id, CaseStatus.TAKEN_OVER)

        self.assertEqual(
            before, svc.repo.get_opportunity("C-1").human_intervention_required
        )

    def test_an_unknown_case_is_reported(self):
        from backend.services import CaseNotFound
        from backend.services.cases import CaseService

        svc = service()
        with self.assertRaises(CaseNotFound):
            CaseService(svc.repo).transition("H-nope", CaseStatus.CLOSED)


class TestPersistenceAcrossARestart(unittest.TestCase):
    """The same service against SQLite, reconnected between messages."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = Path(self.tmpdir) / "backend.db"

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _service(self):
        from backend.storage.sqlite import SqliteRepository

        return service(SqliteRepository(self.db_path))

    def test_a_conversation_continues_after_a_restart(self):
        svc = self._service()
        send(svc, "I want private hospital coverage")
        svc.repo.close()

        svc = self._service()
        result = send(svc, "How much is the Plus plan?")
        self.assertEqual(2, result.opportunity.customer_message_count)
        self.assertIs(Product.PLUS, result.opportunity.product)
        svc.repo.close()

    def test_idempotency_survives_a_restart(self):
        svc = self._service()
        first = send(svc, "hello", key="k-restart")
        svc.repo.close()

        svc = self._service()
        replay = send(svc, "hello", key="k-restart")
        self.assertTrue(replay.replayed)
        self.assertEqual(first.to_dict(), replay.to_dict())
        svc.repo.close()


class TestOnlyServicesWritesStorage(unittest.TestCase):
    """§4 rule: `services` is the only package that writes through a repository.

    Concentrating the writes is what makes the transaction boundary and the
    idempotency check meaningful — a write from elsewhere would bypass both.
    """

    WRITE_METHODS = (
        "upsert_opportunity", "delete_opportunity", "add_case", "update_case",
        "save_message_receipt", "save_agent_run",
    )

    def test_no_package_outside_services_calls_a_write_method(self):
        import ast
        import pathlib

        import backend

        root = pathlib.Path(backend.__file__).parent
        offenders = []
        for path in root.rglob("*.py"):
            parts = path.relative_to(root).parts
            package = parts[0] if len(parts) > 1 else None
            if package in ("services", "tests") or "__pycache__" in parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in self.WRITE_METHODS
                ):
                    # The repositories themselves define these methods; calling one
                    # from inside storage is the implementation, not a bypass.
                    if package == "storage":
                        continue
                    offenders.append(
                        f"{path.relative_to(root)}:{node.lineno} {node.func.attr}"
                    )
        self.assertEqual([], offenders, "\n".join(offenders))


class TestHandoffConfirmation(unittest.TestCase):
    """Test the handoff confirmation flow (Kevin-work feature 2).

    When escalation is triggered, the system now requests customer confirmation
    before creating a case, giving them one more chance to reconsider.
    """

    def test_handoff_answer_recognizes_confirm(self):
        """Confirm keywords return True."""
        from backend.services.conversation import ConversationService

        self.assertTrue(ConversationService._handoff_answer("Confirm"))
        self.assertTrue(ConversationService._handoff_answer("Yes"))
        self.assertTrue(ConversationService._handoff_answer("yes please"))
        self.assertTrue(ConversationService._handoff_answer("确认"))
        self.assertTrue(ConversationService._handoff_answer("是"))
        self.assertTrue(ConversationService._handoff_answer("好的"))
        # Case insensitive and strips punctuation
        self.assertTrue(ConversationService._handoff_answer("CONFIRM!"))
        self.assertTrue(ConversationService._handoff_answer("Yes."))

    def test_handoff_answer_recognizes_cancel(self):
        """Cancel keywords return False."""
        from backend.services.conversation import ConversationService

        self.assertFalse(ConversationService._handoff_answer("Cancel"))
        self.assertFalse(ConversationService._handoff_answer("No"))
        self.assertFalse(ConversationService._handoff_answer("no thanks"))
        self.assertFalse(ConversationService._handoff_answer("取消"))
        self.assertFalse(ConversationService._handoff_answer("否"))
        self.assertFalse(ConversationService._handoff_answer("不用"))
        # Case insensitive and strips punctuation
        self.assertFalse(ConversationService._handoff_answer("CANCEL!"))
        self.assertFalse(ConversationService._handoff_answer("No."))

    def test_handoff_answer_returns_none_for_other_input(self):
        """Other input returns None (treated as new question)."""
        from backend.services.conversation import ConversationService

        self.assertIsNone(ConversationService._handoff_answer("How much?"))
        self.assertIsNone(ConversationService._handoff_answer("Tell me more"))
        self.assertIsNone(ConversationService._handoff_answer("I need life insurance"))
        self.assertIsNone(ConversationService._handoff_answer("Maybe"))

    def test_handoff_chips_returns_confirm_and_cancel(self):
        """Handoff chips provide Confirm and Cancel buttons."""
        from backend.services.conversation import ConversationService

        chips = ConversationService._handoff_chips()
        self.assertEqual(len(chips), 2)
        labels = [c.label for c in chips]
        self.assertIn("Confirm", labels)
        self.assertIn("Cancel", labels)
        # Verify they have IDs
        ids = [c.id for c in chips]
        self.assertIn("handoff_confirm", ids)
        self.assertIn("handoff_cancel", ids)

    def test_escalation_sets_pending_instead_of_creating_case(self):
        """When escalation is triggered, set pending_handoff_reason instead of creating case."""
        svc = service()
        send(svc, "I want to speak to a human agent")

        opp = svc.repo.get_opportunity("C-1")
        # Should set pending_handoff_reason
        self.assertIsNotNone(opp.pending_handoff_reason)
        self.assertTrue(opp.human_intervention_required)
        # Should NOT create a case yet
        self.assertIsNone(svc.repo.active_case_for("C-1"))
        self.assertEqual([], svc.repo.list_cases())

    def test_confirmation_prompt_is_returned(self):
        """After escalation, the system returns a confirmation prompt."""
        svc = service()
        result = send(svc, "I want to speak to a human agent")

        # Should return confirmation prompt
        self.assertIn("notify", result.reply.text.lower())
        self.assertIn("confirm", result.reply.text.lower())
        self.assertIn("cancel", result.reply.text.lower())
        # Should provide quick reply buttons
        labels = [c.label for c in result.quick_replies]
        self.assertIn("Confirm", labels)
        self.assertIn("Cancel", labels)

    def test_customer_confirm_creates_case(self):
        """Customer confirms → case is created, takeover = True."""
        svc = service()
        send(svc, "I want to speak to a human agent")
        result = send(svc, "Confirm")

        # Case should be created
        case = svc.repo.active_case_for("C-1")
        self.assertIsNotNone(case)
        # Reason should contain customer's request
        self.assertTrue(len(case.reason) > 0)

        # Opportunity should be under takeover
        opp = svc.repo.get_opportunity("C-1")
        self.assertTrue(opp.human_takeover)
        self.assertIsNone(opp.pending_handoff_reason)

        # Reply should confirm handoff
        self.assertIn("representative", result.reply.text.lower())
        self.assertIn("contact", result.reply.text.lower())

    def test_customer_cancel_clears_pending(self):
        """Customer cancels → pending cleared, continue AI conversation."""
        svc = service()
        send(svc, "I want to speak to a human agent")
        result = send(svc, "Cancel")

        # Case should NOT be created
        self.assertIsNone(svc.repo.active_case_for("C-1"))
        self.assertEqual([], svc.repo.list_cases())

        # Pending should be cleared
        opp = svc.repo.get_opportunity("C-1")
        self.assertIsNone(opp.pending_handoff_reason)
        self.assertFalse(opp.human_takeover)

        # Reply should acknowledge cancellation
        self.assertIn("understood", result.reply.text.lower())
        self.assertIn("help", result.reply.text.lower())

    def test_other_response_supersedes_handoff_offer(self):
        """Customer replies with other content → pending cleared, treated as new question."""
        svc = service()
        send(svc, "I want to speak to a human agent")
        result = send(svc, "How much is the Plus plan?")

        # Case should NOT be created
        self.assertIsNone(svc.repo.active_case_for("C-1"))

        # Pending should be cleared
        opp = svc.repo.get_opportunity("C-1")
        self.assertIsNone(opp.pending_handoff_reason)

        # Should process as new question (not a handoff response)
        # The reply should be about the Plus plan
        self.assertTrue(len(result.reply.text) > 0)

    def test_existing_case_is_updated_not_pending(self):
        """When there's already an active case, update it directly without confirmation."""
        svc = service()
        # First escalation with confirmation
        send(svc, "I want to speak to a human agent")
        send(svc, "Confirm")

        # Verify case exists
        first_case = svc.repo.active_case_for("C-1")
        self.assertIsNotNone(first_case)
        first_reason = first_case.reason

        # Second escalation should update the case directly
        result = send(svc, "Can you give me a discount?")

        # Should NOT set pending (case already exists)
        opp = svc.repo.get_opportunity("C-1")
        self.assertIsNone(opp.pending_handoff_reason)

        # Should update the existing case
        updated_case = svc.repo.active_case_for("C-1")
        self.assertIsNotNone(updated_case)
        self.assertEqual(first_case.id, updated_case.id)
        # Reason should be updated
        self.assertNotEqual(first_reason, updated_case.reason)

    def test_chinese_confirm_works(self):
        """Chinese confirmation keywords work correctly."""
        svc = service()
        send(svc, "I want to speak to a human agent")
        result = send(svc, "确认")

        # Case should be created
        self.assertIsNotNone(svc.repo.active_case_for("C-1"))
        opp = svc.repo.get_opportunity("C-1")
        self.assertTrue(opp.human_takeover)

    def test_chinese_cancel_works(self):
        """Chinese cancellation keywords work correctly."""
        svc = service()
        send(svc, "I want to speak to a human agent")
        result = send(svc, "取消")

        # Case should NOT be created
        self.assertIsNone(svc.repo.active_case_for("C-1"))
        opp = svc.repo.get_opportunity("C-1")
        self.assertFalse(opp.human_takeover)
        self.assertIsNone(opp.pending_handoff_reason)


if __name__ == "__main__":
    unittest.main()
