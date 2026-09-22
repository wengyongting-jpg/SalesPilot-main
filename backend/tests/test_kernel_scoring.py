# -*- coding: utf-8 -*-
"""P2: the two-axis score, the qualification gate, and the priority matrix.

Specification: `docs/backend-contract.md` gap register item 13.

The scenarios that open this file are the ones that justified the redesign. Run
against the frozen build they produced:

    advertising spam, no insurance words   66  MEDIUM   (and it burned a human case)
    advertising spam, insurance words      96  HIGH
    a genuine high-intent customer         82  HIGH

Spam outranked the real customer. These tests fail if that ordering ever returns.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from backend.domain.detection import Detection
from backend.domain.enums import (
    Intent,
    OpportunityState,
    Priority,
    Product,
    Qualification,
    Signal,
)
from backend.domain.message import Message
from backend.domain.opportunity import Opportunity

NOW = datetime(2026, 9, 22, 12, 0, 0)


def opportunity(
    *,
    product=Product.UNKNOWN,
    state=OpportunityState.COLD_LEAD,
    signals=(),
    best_intent=Intent.GENERIC,
    customer_messages=1,
    last_seen_hours_ago=0.0,
    solicitation_count=0,
    qualification=Qualification.QUALIFIED,
    expansion=(),
) -> Opportunity:
    """An opportunity with a transcript consistent with its counters.

    The transcript matters: engagement recency is derived from the last customer
    message rather than stored, so a fixture that sets a counter without messages
    would be testing something the system never sees.
    """
    opp = Opportunity(id="C-T", customer_name="T", state=state, product=product)
    opp.signals = list(signals)
    opp.signal_history = list(signals)
    opp.best_intent = best_intent
    opp.customer_message_count = customer_messages
    opp.solicitation_count = solicitation_count
    opp.qualification = qualification
    opp.expansion = list(expansion)
    stamp = NOW - timedelta(hours=last_seen_hours_ago)
    for index in range(customer_messages):
        opp.messages.append(Message.from_customer(f"m{index}", ts=stamp))
    return opp


class TestFitAxis(unittest.TestCase):
    """Fit answers "how valuable and how appropriate", not "how warm"."""

    def test_an_unidentified_need_scores_no_fit(self):
        from backend.kernel import scoring

        card = scoring.score(
            opportunity(), Detection(intent=Intent.GENERIC), "hello", now=NOW
        )
        self.assertEqual(0, card.need_identified)
        self.assertEqual(0, card.product_potential)
        self.assertEqual(0, card.fit_total)

    def test_product_potential_tracks_deal_size(self):
        from backend.kernel import scoring

        seen = {}
        for product in (Product.ESSENTIAL, Product.FAMILY, Product.PLUS, Product.CORPORATE):
            card = scoring.score(
                opportunity(product=product, best_intent=Intent.PRICE),
                Detection(intent=Intent.PRICE, product=product),
                "how much",
                now=NOW,
            )
            seen[product] = card.product_potential
        self.assertLess(seen[Product.ESSENTIAL], seen[Product.FAMILY])
        self.assertLess(seen[Product.FAMILY], seen[Product.PLUS])
        self.assertLess(seen[Product.PLUS], seen[Product.CORPORATE])

    def test_product_potential_and_expansion_are_fit_not_behaviour(self):
        """They describe the opportunity's worth, so they belong to the fit axis.

        Leaving them in the behavioural total is what let a noisy conversation
        about an expensive plan look like an active buyer.
        """
        from backend.kernel import scoring

        card = scoring.score(
            opportunity(
                product=Product.CORPORATE,
                best_intent=Intent.CORPORATE_NEED,
                signals=(Signal.EXPANSION_CORPORATE,),
            ),
            Detection(intent=Intent.CORPORATE_NEED, product=Product.CORPORATE,
                      signals=[Signal.EXPANSION_CORPORATE]),
            "we have 120 employees",
            now=NOW,
        )
        self.assertGreater(card.product_potential, 0)
        self.assertGreater(card.expansion, 0)
        self.assertEqual(
            card.fit_total,
            card.need_identified + card.product_potential + card.expansion,
        )
        # Behaviour is the raw sum scaled by recency: decay multiplies the axis
        # rather than contributing a term to it.
        self.assertEqual(
            card.behaviour_raw,
            card.purchase_intent + card.purchase_readiness + card.engagement,
        )
        self.assertEqual(
            card.behaviour_total,
            round(card.behaviour_raw * card.engagement_recency / 100),
        )


class TestEngagementDecay(unittest.TestCase):
    """The dimension is named "Engagement & Urgency"; it must involve time."""

    def _engagement(self, hours_ago: float, messages: int = 5):
        from backend.kernel import scoring

        return scoring.score(
            opportunity(
                product=Product.PLUS,
                best_intent=Intent.PRICE,
                customer_messages=messages,
                last_seen_hours_ago=hours_ago,
            ),
            Detection(intent=Intent.PRICE, product=Product.PLUS),
            "how much",
            now=NOW,
        )

    def test_a_stale_conversation_scores_lower_than_a_fresh_one(self):
        fresh = self._engagement(hours_ago=0.5)
        week_old = self._engagement(hours_ago=24 * 9)
        # Raw engagement is unchanged — the same messages were exchanged. What
        # changes is how much that evidence still counts.
        self.assertEqual(fresh.engagement, week_old.engagement)
        self.assertGreater(fresh.engagement_recency, week_old.engagement_recency)
        self.assertGreater(fresh.behaviour_total, week_old.behaviour_total)

    def test_decay_is_monotonic(self):
        ages = [0.5, 12, 48, 24 * 5, 24 * 30]
        values = [self._engagement(hours_ago=age).engagement_recency for age in ages]
        self.assertEqual(sorted(values, reverse=True), values, values)

    def test_depth_has_diminishing_returns_and_a_ceiling(self):
        depths = [self._engagement(0.5, messages=n).engagement_depth
                  for n in (1, 2, 3, 5, 8, 40)]
        self.assertEqual(sorted(depths), depths, "depth must not decrease")
        self.assertEqual(depths[-1], depths[-2], "depth must plateau, not run away")
        self.assertLess(depths[1] - depths[0], depths[-1], "returns must diminish")

    def _genuinely_strong(self, hours_ago: float):
        """An opportunity that really is HIGH when fresh: band A fit and hot behaviour.

        Built explicitly rather than reusing `_engagement`, whose fixture scores fit 70
        — band B since the threshold was raised, so it is not HIGH even when fresh and
        would make the assertion below vacuous.
        """
        from backend.kernel import scoring

        opp = opportunity(
            product=Product.CORPORATE,
            best_intent=Intent.APPLICATION,
            signals=(Signal.PURCHASE,),
            customer_messages=4,
            last_seen_hours_ago=hours_ago,
        )
        return scoring.score(
            opp,
            Detection(intent=Intent.APPLICATION, product=Product.CORPORATE,
                      signals=[Signal.PURCHASE]),
            "how do I apply",
            now=NOW,
        )

    def test_a_long_silence_drops_a_strong_opportunity_out_of_high(self):
        """Decay has to be able to move a band, or it is decoration.

        This is why recency multiplies the behaviour axis instead of adding ten
        points to it: as an additive dimension, forty days of silence on a
        well-fitting opportunity still came out HIGH.
        """
        from backend.domain.enums import Priority

        fresh = self._genuinely_strong(hours_ago=0.5)
        abandoned = self._genuinely_strong(hours_ago=24 * 40)
        self.assertIs(Priority.HIGH, fresh.priority)
        self.assertIsNot(Priority.HIGH, abandoned.priority)
        self.assertEqual(fresh.fit_total, abandoned.fit_total, "fit must not decay")
        self.assertLess(abandoned.behaviour_total, fresh.behaviour_total)

    def test_urgency_is_a_high_water_mark_not_a_per_turn_flag(self):
        """Consistent with `best_intent`. The previous build only inspected the
        current message, so "I need this urgently" was forgotten one turn later."""
        from backend.kernel import scoring

        opp = opportunity(product=Product.PLUS, best_intent=Intent.PRICE,
                          customer_messages=2, last_seen_hours_ago=0.5)
        urgent = scoring.score(
            opp, Detection(intent=Intent.PRICE, product=Product.PLUS),
            "I need this urgently", now=NOW,
        )
        self.assertGreater(urgent.engagement_urgency, 0)

        opp.urgency_observed = True
        later = scoring.score(
            opp, Detection(intent=Intent.PRICE, product=Product.PLUS),
            "ok", now=NOW,
        )
        self.assertEqual(urgent.engagement_urgency, later.engagement_urgency)

    def test_scoring_requires_an_injected_clock(self):
        """Recency must not read the wall clock, or the tests become flaky and the
        score becomes unreproducible from stored data."""
        from backend.kernel import scoring

        a = self._engagement(hours_ago=3)
        b = scoring.score(
            opportunity(product=Product.PLUS, best_intent=Intent.PRICE,
                        customer_messages=5, last_seen_hours_ago=3),
            Detection(intent=Intent.PRICE, product=Product.PLUS),
            "how much",
            now=NOW + timedelta(days=365),
        )
        self.assertGreater(a.engagement_recency, b.engagement_recency)


class TestQualificationGate(unittest.TestCase):
    """The machine may hold. Only a human may disqualify."""

    def test_a_normal_enquiry_is_qualified(self):
        from backend.kernel import qualification

        verdict = qualification.assess(
            opportunity(), Detection(intent=Intent.PRICE, product=Product.PLUS)
        )
        self.assertIs(Qualification.QUALIFIED, verdict.level)

    def test_the_machine_never_disqualifies(self):
        """A model judgement can be wrong, so the machine's worst action must be
        reversible with one human click."""
        from backend.kernel import qualification

        blatant = Detection(genuine_enquiry=False, solicitation=True)
        for count in range(0, 6):
            verdict = qualification.assess(
                opportunity(solicitation_count=count), blatant
            )
            self.assertNotEqual(
                Qualification.DISQUALIFIED, verdict.level,
                "only a human may disqualify",
            )

    def test_one_solicitation_alone_does_not_hold(self):
        """Two strikes. A single misjudged message must not cost a real lead."""
        from backend.kernel import qualification

        verdict = qualification.assess(
            opportunity(solicitation_count=0),
            Detection(solicitation=True, genuine_enquiry=True),
        )
        self.assertIs(Qualification.QUALIFIED, verdict.level)

    def test_a_second_solicitation_holds(self):
        from backend.kernel import qualification

        verdict = qualification.assess(
            opportunity(solicitation_count=1),
            Detection(solicitation=True, genuine_enquiry=True),
        )
        self.assertIs(Qualification.HELD, verdict.level)

    def test_blatant_promotion_holds_on_the_first_message(self):
        """Both observations at once: the model says it is not an enquiry and the
        deterministic marker agrees."""
        from backend.kernel import qualification

        verdict = qualification.assess(
            opportunity(solicitation_count=0),
            Detection(solicitation=True, genuine_enquiry=False),
        )
        self.assertIs(Qualification.HELD, verdict.level)

    def test_a_hold_always_carries_reviewable_evidence(self):
        from backend.kernel import qualification

        verdict = qualification.assess(
            opportunity(solicitation_count=1), Detection(solicitation=True)
        )
        self.assertIs(Qualification.HELD, verdict.level)
        self.assertTrue(verdict.reason)
        self.assertTrue(verdict.evidence, "a hold with no evidence is not reviewable")

    def test_a_human_decision_is_never_overturned_by_the_machine(self):
        from backend.kernel import qualification

        disqualified = opportunity(qualification=Qualification.DISQUALIFIED)
        verdict = qualification.assess(disqualified, Detection(intent=Intent.PRICE))
        self.assertIs(Qualification.DISQUALIFIED, verdict.level)

    def test_a_hold_is_not_cleared_by_a_later_innocuous_message(self):
        """Release is a human action. Otherwise a spammer clears its own hold by
        sending one polite sentence."""
        from backend.kernel import qualification

        held = opportunity(qualification=Qualification.HELD, solicitation_count=2)
        verdict = qualification.assess(held, Detection(intent=Intent.PRICE))
        self.assertIs(Qualification.HELD, verdict.level)


class TestPriorityDerivation(unittest.TestCase):
    """Priority comes from the two axes as a matrix, and still has three values."""

    def test_priority_is_one_of_the_three_wire_values(self):
        from backend.kernel import priority

        for fit in (0, 35, 45, 75, 100):
            for behaviour in (0, 35, 45, 75, 100):
                self.assertIn(
                    priority.derive(fit, behaviour, Qualification.QUALIFIED),
                    (Priority.HIGH, Priority.MEDIUM, Priority.LOW),
                )

    def test_strong_behaviour_without_fit_is_not_high(self):
        """This is the spam case in one assertion. Noise alone must not promote."""
        from backend.kernel import priority

        self.assertNotEqual(
            Priority.HIGH,
            priority.derive(fit=20, behaviour=95, qualification=Qualification.QUALIFIED),
        )

    def test_fit_and_behaviour_together_are_high(self):
        from backend.kernel import priority

        self.assertIs(
            Priority.HIGH,
            priority.derive(fit=80, behaviour=80, qualification=Qualification.QUALIFIED),
        )

    def test_one_question_about_a_mid_tier_plan_is_not_yet_high(self):
        """Found by running the API: a first message naming Plus produced fit 70,
        behaviour 41 and came out HIGH.

        HIGH means "call this person now". Awarding it for a single question devalues
        the band and refills the queue with everything, which is the undifferentiated
        state the redesign set out to fix. Band A should mean a clearly valuable and
        well-identified opportunity: a mid-tier plan named once is not that yet.
        """
        from backend.kernel import priority

        self.assertIsNot(
            Priority.HIGH,
            priority.derive(fit=70, behaviour=41, qualification=Qualification.QUALIFIED),
        )

    def test_a_larger_opportunity_still_reaches_band_a(self):
        from backend.kernel import priority

        # Corporate: need 40 + product 40 = 80. Plus with family expansion: 40+30+13.
        for fit in (80, 83):
            self.assertEqual(
                "A", priority.fit_band(fit), f"fit {fit} should be band A"
            )
        self.assertEqual("B", priority.fit_band(70))

    def test_sustained_engagement_still_reaches_high_at_band_b(self):
        """Raising the A threshold must not make HIGH unreachable for a real buyer
        who happens to want a mid-tier plan."""
        from backend.kernel import priority

        self.assertIs(
            Priority.HIGH,
            priority.derive(fit=73, behaviour=82, qualification=Qualification.QUALIFIED),
        )

    def test_a_held_conversation_is_never_ranked_above_low(self):
        from backend.kernel import priority

        for level in (Qualification.HELD, Qualification.DISQUALIFIED):
            self.assertIs(
                Priority.LOW,
                priority.derive(fit=100, behaviour=100, qualification=level),
                f"{level.value} must not outrank anything",
            )

    def test_a_dormant_opportunity_is_not_top_of_the_queue(self):
        """Found end to end: a customer who said "let me think about it" reached
        Dormant/Lost and still came out HIGH, because priority read only the two
        axes and never the state.

        The state machine has already concluded this conversation is not live. A
        representative's next call should not be to somebody who just asked for time.
        """
        from backend.kernel import priority

        self.assertIs(
            Priority.HIGH,
            priority.derive(fit=80, behaviour=50, qualification=Qualification.QUALIFIED,
                            state=OpportunityState.EVALUATION_HESITATION),
        )
        self.assertIsNot(
            Priority.HIGH,
            priority.derive(fit=80, behaviour=50, qualification=Qualification.QUALIFIED,
                            state=OpportunityState.DORMANT_LOST),
        )

    def test_a_dormant_opportunity_keeps_its_value_for_re_engagement(self):
        """Capped, not zeroed. The opportunity may be worth reviving later, which is
        what the Dormant/Lost state and a re-engagement follow-up are for."""
        from backend.kernel import priority

        self.assertIs(
            Priority.MEDIUM,
            priority.derive(fit=95, behaviour=95, qualification=Qualification.QUALIFIED,
                            state=OpportunityState.DORMANT_LOST),
        )

    def test_scoring_passes_the_state_through_to_the_band(self):
        from backend.kernel import scoring

        dormant = opportunity(
            product=Product.CORPORATE, state=OpportunityState.DORMANT_LOST,
            best_intent=Intent.PRICE, customer_messages=3, last_seen_hours_ago=0.2,
        )
        card = scoring.score(
            dormant, Detection(intent=Intent.PRICE, product=Product.CORPORATE),
            "let me think about it", now=NOW,
        )
        self.assertIsNot(Priority.HIGH, card.priority)


class TestTheScenariosThatJustifiedTheRedesign(unittest.TestCase):
    """End-to-end at the kernel level, using the three conversations from the
    gap register. The ordering assertion is the point of the whole redesign."""

    def _score(self, opp, det, text):
        from backend.kernel import qualification, scoring

        verdict = qualification.assess(opp, det)
        opp.qualification = verdict.level
        return scoring.score(opp, det, text, now=NOW)

    def _spam_without_insurance_words(self):
        det = Detection(
            intent=Intent.GENERIC, product=Product.UNKNOWN,
            signals=[Signal.PURCHASE], genuine_enquiry=False, solicitation=True,
        )
        opp = opportunity(customer_messages=5, last_seen_hours_ago=0.2,
                          solicitation_count=4, signals=(Signal.PURCHASE,))
        return self._score(opp, det, "buy cheap watches at example.com"), opp

    def _spam_with_insurance_words(self):
        det = Detection(
            intent=Intent.APPLICATION, product=Product.CORPORATE,
            signals=[Signal.PURCHASE, Signal.EXPANSION_CORPORATE],
            genuine_enquiry=False, solicitation=True,
        )
        opp = opportunity(
            product=Product.CORPORATE, state=OpportunityState.HIGH_INTENT,
            best_intent=Intent.APPLICATION, customer_messages=5,
            last_seen_hours_ago=0.2, solicitation_count=4,
            signals=(Signal.PURCHASE, Signal.EXPANSION_CORPORATE),
            expansion=("Corporate",),
        )
        return self._score(opp, det, "we sell insurance leads, apply now"), opp

    def _genuine_customer(self):
        det = Detection(
            intent=Intent.APPLICATION, product=Product.PLUS,
            signals=[Signal.PURCHASE, Signal.EXPANSION_FAMILY],
        )
        opp = opportunity(
            product=Product.PLUS, state=OpportunityState.HIGH_INTENT,
            best_intent=Intent.APPLICATION, customer_messages=4,
            last_seen_hours_ago=0.2,
            signals=(Signal.PURCHASE, Signal.EXPANSION_FAMILY),
            expansion=("Family",),
        )
        return self._score(opp, det, "okay, how do I apply?"), opp

    def test_spam_is_held_and_leaves_the_queue(self):
        for label, builder in (
            ("without insurance words", self._spam_without_insurance_words),
            ("with insurance words", self._spam_with_insurance_words),
        ):
            with self.subTest(label):
                card, opp = builder()
                self.assertIs(Qualification.HELD, opp.qualification)
                self.assertFalse(opp.is_sellable)
                self.assertIs(Priority.LOW, card.priority)

    def test_a_genuine_customer_is_qualified_and_ranked(self):
        card, opp = self._genuine_customer()
        self.assertIs(Qualification.QUALIFIED, opp.qualification)
        self.assertTrue(opp.is_sellable)
        self.assertIs(Priority.HIGH, card.priority)

    def test_spam_never_outranks_a_genuine_customer(self):
        """The defect in one assertion. On the frozen build spam scored 96 and the
        genuine customer 82."""
        genuine, _ = self._genuine_customer()
        for label, builder in (
            ("without insurance words", self._spam_without_insurance_words),
            ("with insurance words", self._spam_with_insurance_words),
        ):
            with self.subTest(label):
                spam, _ = builder()
                self.assertLess(
                    spam.behaviour_total + spam.fit_total,
                    genuine.behaviour_total + genuine.fit_total,
                    "spam must not outrank a genuine customer on either axis sum",
                )

    def test_the_display_total_is_never_used_to_rank(self):
        """`total` exists for the wire. Ranking is the matrix, so a held
        conversation with a high total still sits at LOW."""
        card, opp = self._spam_with_insurance_words()
        self.assertIs(Priority.LOW, card.priority)
        self.assertEqual(
            card.total, round((card.fit_total + card.behaviour_total) / 2)
        )


if __name__ == "__main__":
    unittest.main()
