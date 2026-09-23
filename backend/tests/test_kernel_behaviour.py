# -*- coding: utf-8 -*-
"""P2: state machine, takeover freeze, next best action, HITL, quick replies.

These are ports rather than redesigns, so the specification is the behaviour of the
frozen build — specifically the fixes labelled P0-1 to P0-4, whose only executable
record is a suite that is being retired. Each is restated here as an assertion so
the rebuild cannot silently reintroduce a bug that was already paid for:

    P0-1  a price concern is hesitation, not a negotiation, and does not escalate
    P0-2  a competitor mention alone does not escalate
    P0-3  human takeover persists, freezes the customer-facing state, and never
          produces a second active case
    P0-4  a discount or price-match request escalates *as a negotiation*, and its
          reason is never reported as medical, underwriting or compliance

Two behaviours are new, from gap register item 13: a held conversation is not sold
to, and a held conversation still escalates a complaint to a person.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from backend.domain.detection import Detection, RetrievalResult
from backend.domain.enums import (
    Intent,
    OpportunityState,
    Priority,
    Product,
    Qualification,
    Signal,
)
from backend.domain.message import Message
from backend.domain.opportunity import Opportunity, ScoreCard

NOW = datetime(2026, 9, 22, 12, 0)


def opportunity(
    *,
    state=OpportunityState.COLD_LEAD,
    product=Product.UNKNOWN,
    signals=(),
    priority=Priority.LOW,
    human_takeover=False,
    qualification=Qualification.QUALIFIED,
    competitive_risk=False,
    churn_risk=False,
    messages=1,
) -> Opportunity:
    opp = Opportunity(id="C-B", customer_name="B", state=state, product=product)
    opp.signals = list(signals)
    opp.signal_history = list(signals)
    opp.human_takeover = human_takeover
    opp.qualification = qualification
    opp.competitive_risk = competitive_risk
    opp.churn_risk = churn_risk
    opp.customer_message_count = messages
    opp.score = ScoreCard(priority=priority, fit_total=50, behaviour_total=50, total=50)
    for index in range(messages):
        opp.messages.append(
            Message.from_customer(f"m{index}", ts=NOW - timedelta(minutes=5))
        )
    return opp


class TestStateMachine(unittest.TestCase):
    """Six states. A detected signal does not by itself move the state."""

    def _move(self, current, det, **kwargs):
        from backend.kernel import state_machine

        return state_machine.transition(current, det, **kwargs)

    def test_a_generic_opening_stays_cold(self):
        result = self._move(OpportunityState.COLD_LEAD, Detection(intent=Intent.GENERIC))
        self.assertIs(OpportunityState.COLD_LEAD, result.new_state)

    def test_an_identified_need_leaves_cold(self):
        result = self._move(OpportunityState.COLD_LEAD, Detection(intent=Intent.PRICE))
        self.assertIs(OpportunityState.POTENTIAL_INTEREST, result.new_state)

    def test_evaluating_a_concrete_plan_moves_to_evaluation(self):
        result = self._move(
            OpportunityState.POTENTIAL_INTEREST,
            Detection(intent=Intent.PRICE, product=Product.PLUS),
        )
        self.assertIs(OpportunityState.EVALUATION_HESITATION, result.new_state)

    def test_strong_purchase_preparation_reaches_high_intent(self):
        det = Detection(intent=Intent.APPLICATION, signals=[Signal.PURCHASE])
        for start in (
            OpportunityState.POTENTIAL_INTEREST,
            OpportunityState.EVALUATION_HESITATION,
        ):
            with self.subTest(start.value):
                self.assertIs(
                    OpportunityState.HIGH_INTENT, self._move(start, det).new_state
                )

    def test_mere_interest_does_not_jump_to_high_intent(self):
        """U3 in the frozen build: "I want Plus" is interest, not preparation."""
        result = self._move(
            OpportunityState.COLD_LEAD,
            Detection(intent=Intent.COVERAGE, product=Product.PLUS),
        )
        self.assertIsNot(OpportunityState.HIGH_INTENT, result.new_state)

    def test_a_new_concern_at_high_intent_falls_back_to_evaluation(self):
        result = self._move(
            OpportunityState.HIGH_INTENT, Detection(signals=[Signal.HESITATION])
        )
        self.assertIs(OpportunityState.EVALUATION_HESITATION, result.new_state)

    def test_hesitation_alongside_purchase_keeps_high_intent(self):
        result = self._move(
            OpportunityState.HIGH_INTENT,
            Detection(signals=[Signal.HESITATION, Signal.PURCHASE]),
        )
        self.assertIs(OpportunityState.HIGH_INTENT, result.new_state)

    def test_withdrawal_moves_to_dormant(self):
        result = self._move(
            OpportunityState.HIGH_INTENT, Detection(signals=[Signal.WITHDRAWAL])
        )
        self.assertIs(OpportunityState.DORMANT_LOST, result.new_state)

    def test_withdrawal_by_an_active_customer_is_churn_risk_not_a_lost_lead(self):
        result = self._move(
            OpportunityState.CLOSED_ACTIVE, Detection(signals=[Signal.WITHDRAWAL])
        )
        self.assertIs(OpportunityState.CLOSED_ACTIVE, result.new_state)
        self.assertTrue(result.set_churn_risk)

    def test_conversion_closes_the_opportunity(self):
        result = self._move(
            OpportunityState.HIGH_INTENT, Detection(signals=[Signal.CONVERSION])
        )
        self.assertIs(OpportunityState.CLOSED_ACTIVE, result.new_state)

    def test_an_expansion_request_from_an_active_customer_sets_a_flag_not_a_state(self):
        result = self._move(
            OpportunityState.CLOSED_ACTIVE,
            Detection(signals=[Signal.EXPANSION_FAMILY]),
        )
        self.assertIs(OpportunityState.CLOSED_ACTIVE, result.new_state)
        self.assertEqual("Family", result.set_expansion)

    def test_a_dormant_lead_with_a_new_need_re_engages(self):
        result = self._move(
            OpportunityState.DORMANT_LOST, Detection(intent=Intent.PRICE)
        )
        self.assertIs(OpportunityState.POTENTIAL_INTEREST, result.new_state)

    def test_lifecycle_observations_arrive_as_data_not_as_text(self):
        """The frozen build's state machine imported the signal detector to run two
        text heuristics itself, which inverted the layering. They are observations
        now, and the kernel only reads them."""
        postponed = self._move(
            OpportunityState.EVALUATION_HESITATION, Detection(postponement=True)
        )
        self.assertIs(OpportunityState.DORMANT_LOST, postponed.new_state)

        cancelled = self._move(
            OpportunityState.EVALUATION_HESITATION, Detection(cancellation=True)
        )
        self.assertIs(OpportunityState.DORMANT_LOST, cancelled.new_state)

        churning = self._move(
            OpportunityState.CLOSED_ACTIVE, Detection(cancellation=True)
        )
        self.assertIs(OpportunityState.CLOSED_ACTIVE, churning.new_state)
        self.assertTrue(churning.set_churn_risk)

    def test_every_transition_states_a_reason(self):
        from backend.kernel import state_machine

        for state in OpportunityState:
            result = state_machine.transition(state, Detection())
            self.assertTrue(result.reason, f"{state.value} produced no reason")


class TestTakeoverFreeze(unittest.TestCase):
    """P0-3, extracted from the flags that were threaded through the old method."""

    def _decide(self, opp, det):
        from backend.kernel import takeover

        return takeover.evaluate(opp, det)

    def test_without_takeover_nothing_is_frozen(self):
        decision = self._decide(opportunity(), Detection(intent=Intent.PRICE))
        self.assertFalse(decision.active)
        self.assertFalse(decision.freeze_state)

    def test_under_takeover_a_vague_message_freezes_the_state(self):
        """Otherwise a stray "ok" drags the opportunity back toward a cold lead
        while a representative is working it."""
        decision = self._decide(
            opportunity(state=OpportunityState.HIGH_INTENT, human_takeover=True),
            Detection(intent=Intent.GENERIC),
        )
        self.assertTrue(decision.active)
        self.assertTrue(decision.freeze_state)
        self.assertTrue(decision.preserve_score_floor)

    def test_the_customers_own_lifecycle_decisions_pass_through(self):
        """Withdrawal and conversion are the customer acting, not the AI selling,
        so they move the opportunity even while a human owns the case."""
        for signal in (Signal.WITHDRAWAL, Signal.CONVERSION):
            with self.subTest(signal.value):
                decision = self._decide(
                    opportunity(
                        state=OpportunityState.HIGH_INTENT, human_takeover=True
                    ),
                    Detection(signals=[signal]),
                )
                self.assertTrue(decision.active, "takeover itself must remain active")
                self.assertFalse(decision.freeze_state)
                self.assertTrue(decision.lifecycle_exception)

    def test_a_decision_always_explains_itself(self):
        decision = self._decide(
            opportunity(human_takeover=True), Detection(intent=Intent.GENERIC)
        )
        self.assertTrue(decision.reason)


class TestNextBestAction(unittest.TestCase):
    def _recommend(self, opp, det, escalated=False):
        from backend.kernel import next_best_action

        return next_best_action.recommend(opp, det, escalated=escalated)

    def test_withdrawal_stops_active_follow_up(self):
        action = self._recommend(
            opportunity(state=OpportunityState.DORMANT_LOST, signals=(Signal.WITHDRAWAL,)),
            Detection(signals=[Signal.WITHDRAWAL]),
        )
        self.assertFalse(action.human_intervention_required)
        self.assertIn("stop", action.action.lower())

    def test_takeover_forces_human_handling_even_without_a_new_trigger(self):
        """P0-3: the AI must not resume autonomous selling on a later message just
        because that message did not independently re-trigger escalation."""
        action = self._recommend(
            opportunity(state=OpportunityState.POTENTIAL_INTEREST, human_takeover=True),
            Detection(intent=Intent.PRICE),
        )
        self.assertTrue(action.human_intervention_required)

    def test_a_held_conversation_is_not_sold_to(self):
        action = self._recommend(
            opportunity(
                state=OpportunityState.HIGH_INTENT,
                qualification=Qualification.HELD,
                priority=Priority.HIGH,
            ),
            Detection(intent=Intent.APPLICATION, signals=[Signal.PURCHASE]),
        )
        self.assertFalse(
            action.human_intervention_required,
            "a held conversation does not consume a representative either",
        )
        for word in ("contact sales", "take over", "prioritise"):
            self.assertNotIn(word, action.action.lower())
        self.assertIs(Priority.LOW, action.priority)

    def test_high_intent_with_competitive_risk_asks_for_a_person(self):
        action = self._recommend(
            opportunity(
                state=OpportunityState.HIGH_INTENT,
                signals=(Signal.COMPETITIVE,),
                competitive_risk=True,
                priority=Priority.HIGH,
            ),
            Detection(signals=[Signal.COMPETITIVE]),
        )
        self.assertTrue(action.human_intervention_required)
        self.assertIn("competitive", action.reason.lower())

    def test_a_cold_lead_is_nurtured(self):
        action = self._recommend(opportunity(), Detection(intent=Intent.GENERIC))
        self.assertFalse(action.human_intervention_required)

    def test_churn_risk_on_an_active_customer_asks_for_a_person(self):
        action = self._recommend(
            opportunity(state=OpportunityState.CLOSED_ACTIVE, churn_risk=True),
            Detection(),
        )
        self.assertTrue(action.human_intervention_required)

    def test_every_recommendation_carries_a_reason(self):
        for state in OpportunityState:
            action = self._recommend(opportunity(state=state), Detection())
            self.assertTrue(action.action)
            self.assertTrue(action.reason)


class TestHitl(unittest.TestCase):
    CONFIDENT = RetrievalResult(facts=["f"], confidence=0.9, product=Product.PLUS)

    def _evaluate(self, opp, det, retrieval=None):
        from backend.kernel import hitl

        return hitl.evaluate(opp, det, retrieval or self.CONFIDENT)

    def test_p0_1_a_price_concern_does_not_escalate(self):
        reason = self._evaluate(
            opportunity(state=OpportunityState.EVALUATION_HESITATION, product=Product.PLUS),
            Detection(intent=Intent.PRICE, product=Product.PLUS,
                      signals=[Signal.HESITATION]),
        )
        self.assertIsNone(reason)

    def test_p0_2_a_competitor_mention_alone_does_not_escalate(self):
        reason = self._evaluate(
            opportunity(state=OpportunityState.EVALUATION_HESITATION, product=Product.PLUS),
            Detection(intent=Intent.COMPARISON, product=Product.PLUS,
                      signals=[Signal.COMPETITIVE]),
        )
        self.assertIsNone(reason)

    def test_p0_4_negotiation_escalates_and_is_never_mislabelled(self):
        """The reason a representative reads decides how they prepare. Reporting a
        discount request as a medical matter sends them in wrongly briefed."""
        reason = self._evaluate(
            opportunity(state=OpportunityState.EVALUATION_HESITATION, product=Product.PLUS),
            Detection(intent=Intent.PRICE, product=Product.PLUS,
                      signals=[Signal.NEGOTIATION]),
        )
        self.assertIsNotNone(reason)
        self.assertIn("negotiation", reason.lower())
        for wrong in ("medical", "underwriting", "compliance"):
            self.assertNotIn(wrong, reason.lower())

    def test_an_explicit_request_for_a_person_escalates(self):
        reason = self._evaluate(
            opportunity(), Detection(signals=[Signal.HUMAN_REQUEST])
        )
        self.assertIsNotNone(reason)

    def test_a_complaint_escalates(self):
        reason = self._evaluate(opportunity(), Detection(intent=Intent.COMPLAINT))
        self.assertIsNotNone(reason)

    def test_a_personalised_medical_question_escalates_as_underwriting(self):
        reason = self._evaluate(
            opportunity(product=Product.PLUS), Detection(intent=Intent.UNDERWRITING)
        )
        self.assertIsNotNone(reason)
        self.assertIn("underwriting", reason.lower())
        self.assertNotIn("negotiation", reason.lower())

    def test_weak_retrieval_on_a_specific_question_escalates_rather_than_guesses(self):
        reason = self._evaluate(
            opportunity(product=Product.PLUS),
            Detection(intent=Intent.COVERAGE, product=Product.PLUS),
            RetrievalResult(facts=[], confidence=0.1, product=Product.PLUS),
        )
        self.assertIsNotNone(reason)

    def test_weak_retrieval_on_a_generic_question_does_not_escalate(self):
        reason = self._evaluate(
            opportunity(), Detection(intent=Intent.GENERIC),
            RetrievalResult(facts=[], confidence=0.0),
        )
        self.assertIsNone(reason)

    def test_withdrawal_is_not_an_escalation(self):
        reason = self._evaluate(
            opportunity(state=OpportunityState.DORMANT_LOST),
            Detection(signals=[Signal.WITHDRAWAL]),
        )
        self.assertIsNone(reason)

    def test_a_held_conversation_still_escalates_a_complaint(self):
        """Held is not ignored. Withholding a complaint from a person because a
        model suspected advertising would be the worst possible failure here."""
        reason = self._evaluate(
            opportunity(qualification=Qualification.HELD),
            Detection(intent=Intent.COMPLAINT),
        )
        self.assertIsNotNone(reason)

    def test_a_held_conversation_does_not_escalate_a_sales_opportunity(self):
        """The sales-opportunity trigger exists to win a deal. A held conversation
        must not consume a representative on that basis."""
        reason = self._evaluate(
            opportunity(
                state=OpportunityState.HIGH_INTENT,
                signals=(Signal.COMPETITIVE,),
                competitive_risk=True,
                qualification=Qualification.HELD,
            ),
            Detection(signals=[Signal.COMPETITIVE]),
        )
        self.assertIsNone(reason)

    # ---- P5: the model's handover proposal is one input among several -------

    def _propose(self, opp, det):
        from backend.domain.detection import HandoffProposal
        from backend.kernel import hitl

        proposal = HandoffProposal(requested=True, reason="customer seems distressed")
        return hitl.evaluate(opp, det, self.CONFIDENT, proposal=proposal)

    def test_a_proposal_is_honoured_for_a_qualified_genuine_enquiry(self):
        from backend.kernel import hitl

        reason = self._propose(opportunity(), Detection(intent=Intent.COVERAGE))
        self.assertIsNotNone(reason)
        self.assertTrue(reason.startswith(hitl.REASON_ASSISTANT_PROPOSED))
        self.assertIn("distressed", reason)

    def test_a_proposal_is_declined_for_a_held_conversation(self):
        reason = self._propose(opportunity(qualification=Qualification.HELD), Detection(intent=Intent.COVERAGE))
        self.assertIsNone(reason)

    def test_a_proposal_is_declined_when_a_person_already_owns_it(self):
        reason = self._propose(opportunity(human_takeover=True), Detection(intent=Intent.COVERAGE))
        self.assertIsNone(reason)

    def test_a_proposal_never_outranks_a_deterministic_reason(self):
        from backend.kernel import hitl

        reason = self._propose(opportunity(), Detection(intent=Intent.COMPLAINT))
        self.assertEqual(reason, hitl.REASON_COMPLAINT)

    def test_no_proposal_changes_nothing(self):
        from backend.kernel import hitl

        opp, det = opportunity(), Detection(intent=Intent.COVERAGE)
        self.assertEqual(hitl.evaluate(opp, det, self.CONFIDENT), hitl.evaluate(opp, det, self.CONFIDENT, proposal=None))


class TestQuickReplies(unittest.TestCase):
    """interface-v1 §5.5. Derived from the deterministic layer, never generated."""

    def _suggest(self, opp, det):
        from backend.kernel import quick_replies

        return quick_replies.suggest(opp, det)

    def test_a_cold_lead_is_offered_between_one_and_three(self):
        chips = self._suggest(opportunity(), Detection(intent=Intent.GENERIC))
        self.assertGreaterEqual(len(chips), 1)
        self.assertLessEqual(len(chips), 3)

    def test_every_label_respects_the_contract_limit(self):
        from backend.kernel import quick_replies

        for chip in quick_replies.catalogue():
            with self.subTest(chip.id):
                self.assertLessEqual(len(chip.label), 24, chip.label)
                self.assertTrue(chip.id.startswith("qr_"))

    def test_ids_are_unique_and_stable(self):
        from backend.kernel import quick_replies

        ids = [chip.id for chip in quick_replies.catalogue()]
        self.assertEqual(len(ids), len(set(ids)))

        first = self._suggest(opportunity(), Detection(intent=Intent.GENERIC))
        again = self._suggest(opportunity(), Detection(intent=Intent.GENERIC))
        self.assertEqual([c.id for c in first], [c.id for c in again])

    def test_no_label_quotes_a_premium_or_offers_advice(self):
        from backend.kernel import quick_replies

        for chip in quick_replies.catalogue():
            with self.subTest(chip.id):
                self.assertNotIn("$", chip.label)
                self.assertNotIn("S$", chip.label)
                for word in ("recommend", "should", "best for you"):
                    self.assertNotIn(word, chip.label.lower())

    def test_none_are_offered_while_a_human_owns_the_conversation(self):
        chips = self._suggest(
            opportunity(state=OpportunityState.HIGH_INTENT, human_takeover=True),
            Detection(intent=Intent.PRICE),
        )
        self.assertEqual([], chips)

    def test_none_are_offered_after_a_withdrawal(self):
        chips = self._suggest(
            opportunity(state=OpportunityState.DORMANT_LOST, signals=(Signal.WITHDRAWAL,)),
            Detection(signals=[Signal.WITHDRAWAL]),
        )
        self.assertEqual([], chips)

    def test_none_are_offered_on_a_restricted_message(self):
        chips = self._suggest(
            opportunity(product=Product.PLUS),
            Detection(intent=Intent.UNDERWRITING, restricted=True),
        )
        self.assertEqual([], chips)

    def test_none_are_offered_to_a_held_conversation(self):
        chips = self._suggest(
            opportunity(qualification=Qualification.HELD),
            Detection(intent=Intent.PRICE),
        )
        self.assertEqual([], chips)

    def test_suggestions_follow_the_state(self):
        cold = self._suggest(opportunity(), Detection(intent=Intent.GENERIC))
        high = self._suggest(
            opportunity(state=OpportunityState.HIGH_INTENT, product=Product.PLUS),
            Detection(intent=Intent.APPLICATION, signals=[Signal.PURCHASE]),
        )
        self.assertNotEqual([c.id for c in cold], [c.id for c in high])


if __name__ == "__main__":
    unittest.main()
