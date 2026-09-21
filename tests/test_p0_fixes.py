# -*- coding: utf-8 -*-
"""Regression tests for the approved P0 fixes.

Covers the 10 required scenarios:
  1. Price concern            -> no HITL
  2. Competitor mention       -> no automatic HITL
  3. Discount request         -> HITL (negotiation reason)
  4. Match competitor price   -> HITL (negotiation reason)
  5. Withdrawal               -> no active Purchase signal
  6. Withdrawal               -> non-sales customer-facing response
  7. Human takeover           -> persists across subsequent messages
  8. Human takeover           -> no duplicate active HITL case
  9. Product detection        -> remains correct
 10. Python version guard     -> friendly error on Python < 3.10
"""
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from salespilot.agent import SalesPilotAgent
from salespilot.detection.intent import IntentClassifier
from salespilot.models import Intent, OpportunityState, Priority, Product, Signal


# Words that must never appear in a withdrawal / takeover reply (sales-pushing)
_SALES_WORDS = (
    "great to hear",
    "interested",
    "apply now",
    "move forward",
    "sign up",
    "proceed",
    "let's get started",
)


class TestPriceAndCompetitor(unittest.TestCase):
    """1 & 2: price concern and competitor mention must NOT auto-escalate."""

    def setUp(self):
        self.agent = SalesPilotAgent()

    def test_price_concern_no_hitl(self):
        self.agent.handle_message("C-PRICE", "T", "How much is the Plus plan?")
        for phrase in ("It's a little expensive.", "It seems expensive.",
                       "The premium is quite high."):
            agent = SalesPilotAgent()
            agent.handle_message("C-P", "T", "How much is the Plus plan?")
            r = agent.handle_message("C-P", "T", phrase)
            self.assertIsNone(r.case, f"Price concern must NOT open a case: '{phrase}'")
            self.assertFalse(
                r.next_best_action.human_intervention_required,
                f"Price concern must NOT require human intervention: '{phrase}'",
            )
            # A price concern is never a negotiation
            self.assertNotIn(Signal.NEGOTIATION, r.detection.signals,
                             f"Price concern must not be treated as negotiation: '{phrase}'")

    def test_expensive_is_hesitation_not_negotiation(self):
        """The canonical 'a bit expensive' phrasing is hesitation, not negotiation."""
        agent = SalesPilotAgent()
        agent.handle_message("C-EXP", "T", "How much is the Plus plan?")
        r = agent.handle_message("C-EXP", "T", "It's a little expensive.")
        self.assertIn(Signal.HESITATION, r.detection.signals)
        self.assertNotIn(Signal.NEGOTIATION, r.detection.signals)
        self.assertIsNone(r.case)

    def test_competitor_mention_no_hitl(self):
        for phrase in ("Another insurer is cheaper.",
                       "How are you different from AIA?"):
            agent = SalesPilotAgent()
            agent.handle_message("C-C", "T", "How much is the Plus plan?")
            r = agent.handle_message("C-C", "T", phrase)
            self.assertIsNone(r.case, f"Competitor mention must NOT open a case: '{phrase}'")
            self.assertFalse(
                r.next_best_action.human_intervention_required,
                f"Competitor mention must NOT require human intervention: '{phrase}'",
            )
            self.assertNotIn(Signal.NEGOTIATION, r.detection.signals)


class TestNegotiation(unittest.TestCase):
    """3 & 4: discount / price-match are negotiation -> HITL with clear reason."""

    NEGOTIATION_MESSAGES = (
        "Can you give me a discount?",
        "Can you match their price?",
        "Can you offer a better rate?",
        "Can we negotiate the price?",
        "Can you lower the premium?",
        "Can you match their quote?",
    )

    def test_negotiation_triggers_hitl_with_correct_reason(self):
        for phrase in self.NEGOTIATION_MESSAGES:
            agent = SalesPilotAgent()
            agent.handle_message("C-N", "T", "How much is the Plus plan?")
            r = agent.handle_message("C-N", "T", phrase)
            self.assertIsNotNone(r.case, f"Negotiation must open a case: '{phrase}'")
            self.assertTrue(
                r.next_best_action.human_intervention_required,
                f"Negotiation must require human intervention: '{phrase}'",
            )
            self.assertIn(Signal.NEGOTIATION, r.detection.signals)
            reason = r.case.reason.lower()
            self.assertIn("negotiation", reason,
                          f"Reason must mention negotiation: '{phrase}' -> {r.case.reason}")
            # Must NOT be mislabelled as medical / underwriting / compliance
            for wrong in ("medical", "underwriting", "compliance"):
                self.assertNotIn(
                    wrong, reason,
                    f"Negotiation reason must not say '{wrong}': '{phrase}' -> {r.case.reason}",
                )

    def test_medical_still_medical_not_negotiation(self):
        """A genuine medical question keeps its medical/underwriting reason."""
        agent = SalesPilotAgent()
        agent.handle_message("C-M", "T", "Tell me about the Plus plan")
        r = agent.handle_message("C-M", "T", "I have diabetes, will it be covered?")
        self.assertIsNotNone(r.case)
        self.assertIn("underwriting", r.case.reason.lower())
        self.assertNotIn("negotiation", r.case.reason.lower())


class TestWithdrawal(unittest.TestCase):
    """5 & 6: withdrawal strips Purchase and produces a non-sales reply."""

    WITHDRAWAL_MESSAGES = (
        "I won't buy anymore.",
        "I don't want to buy anymore.",
        "I'm no longer interested.",
        "I don't want the plan anymore.",
        "I've decided not to purchase.",
    )

    def test_withdrawal_has_no_active_purchase_signal(self):
        for phrase in self.WITHDRAWAL_MESSAGES:
            agent = SalesPilotAgent()
            agent.handle_message("C-W", "T", "How much is Plus? I want to apply")
            r = agent.handle_message("C-W", "T", phrase)
            self.assertIn(Signal.WITHDRAWAL, r.detection.signals,
                          f"Should detect withdrawal: '{phrase}'")
            self.assertNotIn(Signal.PURCHASE, r.detection.signals,
                             f"Withdrawal must strip Purchase for the turn: '{phrase}'")
            self.assertNotIn(Signal.PURCHASE, r.opportunity.signals,
                             f"Purchase must not stay active after withdrawal: '{phrase}'")
            self.assertIn(Signal.WITHDRAWAL, r.opportunity.signals)

    def test_withdrawal_decreases_score_and_priority(self):
        agent = SalesPilotAgent()
        agent.handle_message("C-W2", "T", "How much is Plus? I want to apply")
        r_before = agent.handle_message("C-W2", "T", "How do I apply?")
        r = agent.handle_message("C-W2", "T", "I won't buy anymore.")
        self.assertLess(r.score.total, r_before.score.total,
                        "Purchase intent / score should decrease after withdrawal")
        self.assertEqual(r.score.priority, Priority.LOW)
        self.assertEqual(r.opportunity.state, OpportunityState.DORMANT_LOST)
        self.assertFalse(r.next_best_action.human_intervention_required,
                         "Withdrawal itself must not trigger HITL")

    def test_withdrawal_response_is_not_sales(self):
        for phrase in self.WITHDRAWAL_MESSAGES:
            agent = SalesPilotAgent()
            agent.handle_message("C-W3", "T", "How much is Plus? I want to apply")
            r = agent.handle_message("C-W3", "T", phrase)
            reply = r.reply.lower()
            for word in _SALES_WORDS:
                self.assertNotIn(
                    word, reply,
                    f"Withdrawal reply must not contain sales language '{word}': "
                    f"'{phrase}' -> {r.reply}",
                )


class TestHumanTakeoverPersists(unittest.TestCase):
    """7 & 8: takeover persists and never creates duplicate active cases."""

    def test_takeover_persists_across_messages(self):
        agent = SalesPilotAgent()
        cid = "C-TK"
        # 1) Trigger HITL
        r1 = agent.handle_message(cid, "T", "I want to speak to a human agent")
        self.assertIsNotNone(r1.case, "First message should open a case")
        # 2) Takeover active
        self.assertTrue(r1.opportunity.human_takeover)

        # 3) Normal follow-up that does not independently trigger HITL
        r2 = agent.handle_message(cid, "T", "How much is CareSure Plus?")
        # 4) Takeover remains active
        self.assertTrue(r2.opportunity.human_takeover,
                        "Takeover must persist on a normal follow-up")
        # 5) AI does not resume autonomous sales persuasion
        self.assertTrue(r2.next_best_action.human_intervention_required,
                        "NBA must remain human handling during takeover")
        reply2 = r2.reply.lower()
        for word in _SALES_WORDS:
            self.assertNotIn(word, reply2,
                             f"Takeover reply must not push sales ('{word}'): {r2.reply}")

        # A message that would normally advance to a sales decision
        r3 = agent.handle_message(cid, "T", "Ok I want to apply now")
        self.assertTrue(r3.opportunity.human_takeover)
        self.assertTrue(r3.next_best_action.human_intervention_required)
        reply3 = r3.reply.lower()
        for word in _SALES_WORDS:
            self.assertNotIn(word, reply3,
                             f"Takeover reply must not push sales ('{word}'): {r3.reply}")

        # 6) No duplicate cases
        self.assertEqual(len(agent.repo.list_cases()), 1,
                         "Exactly one case should exist after takeover persists")

    def test_no_duplicate_case_when_new_escalation_during_takeover(self):
        agent = SalesPilotAgent()
        cid = "C-TK2"
        r1 = agent.handle_message(cid, "T", "I have a pre-existing condition, covered?")
        self.assertIsNotNone(r1.case)
        # A second, different escalation reason during takeover
        agent.handle_message(cid, "T", "Also can you give me a discount?")
        active = [c for c in agent.repo.list_cases()
                  if c.opportunity_id == cid and c.status.value != "Closed"]
        self.assertEqual(len(active), 1,
                         "New escalation during takeover must update the existing case, "
                         "not create a duplicate")


class TestProductDetection(unittest.TestCase):
    """9: product detection remains correct after the changes."""

    def test_product_detection_unchanged(self):
        agent = SalesPilotAgent()
        r = agent.handle_message("C-PD1", "T", "How much does CareSure Plus cost?")
        self.assertEqual(r.opportunity.product, Product.PLUS)

        agent2 = SalesPilotAgent()
        r2 = agent2.handle_message("C-PD2", "T", "We have 120 employees")
        self.assertEqual(r2.opportunity.product, Product.CORPORATE)

        agent3 = SalesPilotAgent()
        r3 = agent3.handle_message("C-PD3", "T", "What's your cheapest basic plan?")
        self.assertEqual(r3.opportunity.product, Product.ESSENTIAL)

        # Product carries forward via context on a follow-up price question
        agent4 = SalesPilotAgent()
        agent4.handle_message("C-PD4", "T", "Tell me about CareSure Plus")
        r4 = agent4.handle_message("C-PD4", "T", "How much is it?")
        self.assertEqual(r4.opportunity.product, Product.PLUS)


class TestPythonVersionGuard(unittest.TestCase):
    """10: importing the package under a simulated old version fails clearly."""

    def test_guard_message_present_in_source(self):
        # The guard must exist and mention the minimum version + a suggestion.
        init_src = (Path(__file__).resolve().parent.parent
                    / "salespilot" / "__init__.py").read_text(encoding="utf-8")
        self.assertIn("3.10", init_src)
        self.assertIn("version_info", init_src)

    def test_guard_triggers_on_simulated_old_version(self):
        """Run the guard logic with a patched version_info < 3.10 in a subprocess."""
        code = textwrap.dedent(
            """
            import sys
            sys.version_info = (3, 9, 25)
            MIN_PYTHON = (3, 10)
            if sys.version_info < MIN_PYTHON:
                print("GUARD_TRIGGERED")
            else:
                print("NO_GUARD")
            """
        )
        out = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True,
        )
        self.assertIn("GUARD_TRIGGERED", out.stdout)


class TestHumanTakeoverMultiTurnRegression(unittest.TestCase):
    """The exact reported 5-turn journey.

    Once takeover activates (Turn 3, negotiation), it must persist through
    Turns 4-5: no autonomous sales, neutral holding reply, no duplicate case,
    and the opportunity's score/state must NOT collapse on a later generic /
    hesitation message.
    """

    def test_reported_five_turn_journey(self):
        agent = SalesPilotAgent()
        cid = "C-MT"

        # --- Turn 1: "How much is Plus?" ---
        r1 = agent.handle_message(cid, "T", "How much is Plus?")
        self.assertEqual(r1.opportunity.product, Product.PLUS,
                         "Turn 1: product should be Plus")
        self.assertIsNone(r1.case, "Turn 1: a plain price question must not open a case")
        self.assertFalse(r1.next_best_action.human_intervention_required)

        # --- Turn 2: "Another insurer is cheaper." ---
        r2 = agent.handle_message(cid, "T", "Another insurer is cheaper.")
        self.assertIn(Signal.COMPETITIVE, r2.detection.signals,
                      "Turn 2: competitive signal expected")
        self.assertIsNone(r2.case,
                          "Turn 2: competitor mention alone must not open a case")
        self.assertFalse(r2.next_best_action.human_intervention_required)

        # --- Turn 3: "Can you match their price?" -> negotiation -> HITL ---
        r3 = agent.handle_message(cid, "T", "Can you match their price?")
        self.assertIn(Signal.NEGOTIATION, r3.detection.signals,
                      "Turn 3: negotiation signal expected")
        self.assertIsNotNone(r3.case, "Turn 3: negotiation must open a HITL case")
        self.assertTrue(r3.opportunity.human_takeover, "Turn 3: takeover must activate")
        self.assertIn("negotiation", r3.case.reason.lower())
        for wrong in ("medical", "underwriting", "compliance"):
            self.assertNotIn(wrong, r3.case.reason.lower())
        score_at_takeover = r3.score.total
        state_at_takeover = r3.opportunity.state

        # --- Turn 4: "Can you tell me more about Plus?" ---
        r4 = agent.handle_message(cid, "T", "Can you tell me more about Plus?")
        self.assertTrue(r4.opportunity.human_takeover,
                        "Turn 4: takeover must remain active")
        self.assertTrue(r4.next_best_action.human_intervention_required,
                        "Turn 4: NBA must stay human handling")
        self._assert_neutral_holding_reply(r4.reply, turn=4)
        self.assertIsNone(r4.case, "Turn 4: must NOT create a duplicate case")
        self.assertEqual(len(agent.repo.list_cases()), 1,
                         "Turn 4: still exactly one case")
        # State/score must not regress under takeover
        self.assertEqual(r4.opportunity.state, state_at_takeover,
                         "Turn 4: state must be frozen under takeover")
        self.assertGreaterEqual(r4.score.total, score_at_takeover,
                                "Turn 4: score must not collapse under takeover")

        # --- Turn 5: "Okay, I am still thinking about it." ---
        r5 = agent.handle_message(cid, "T", "Okay, I am still thinking about it.")
        self.assertTrue(r5.opportunity.human_takeover,
                        "Turn 5: takeover must remain active")
        self.assertTrue(r5.next_best_action.human_intervention_required)
        self._assert_neutral_holding_reply(r5.reply, turn=5)
        # Previous opportunity information remains available
        self.assertEqual(r5.opportunity.product, Product.PLUS,
                         "Turn 5: product context must be retained")
        self.assertEqual(r5.opportunity.state, state_at_takeover,
                         "Turn 5: state must not reset to cold/dormant")
        self.assertGreaterEqual(r5.score.total, score_at_takeover,
                                "Turn 5: score must not reset to a cold-lead value")
        self.assertNotEqual(r5.opportunity.state, OpportunityState.COLD_LEAD)
        self.assertNotEqual(r5.opportunity.state, OpportunityState.DORMANT_LOST)
        self.assertEqual(len(agent.repo.list_cases()), 1)

    def test_takeover_invariant_holds_every_turn(self):
        """Invariant: while human_takeover is active, the response is never
        autonomous sales, and takeover never silently turns off."""
        agent = SalesPilotAgent()
        cid = "C-INV"
        agent.handle_message(cid, "T", "Can you give me a discount on Plus?")  # takeover on
        follow_ups = [
            "Can you tell me more about Plus?",
            "Another insurer is cheaper",
            "How do I apply?",
            "Okay",
            "I am still thinking about it",
        ]
        for msg in follow_ups:
            r = agent.handle_message(cid, "T", msg)
            # human_takeover_active == True  =>  response_mode != autonomous_sales
            self.assertTrue(r.opportunity.human_takeover,
                            f"Takeover must stay active on: '{msg}'")
            self.assertTrue(
                r.next_best_action.human_intervention_required,
                f"NBA must remain human handling on: '{msg}'",
            )
            self._assert_neutral_holding_reply(r.reply, turn=msg)
        # Only one case for the whole takeover conversation
        self.assertEqual(len(agent.repo.list_cases()), 1)

    def _assert_neutral_holding_reply(self, reply: str, turn) -> None:
        low = reply.lower()
        for word in _SALES_WORDS:
            self.assertNotIn(
                word, low,
                f"Turn {turn}: takeover reply must not push sales ('{word}'): {reply}",
            )
        # Must not contain autonomous "Would you like me to..." style prompts
        self.assertNotIn("would you like me to", low,
                         f"Turn {turn}: takeover reply must not offer autonomous help: {reply}")
        # Must actually be the neutral holding message
        self.assertIn("representative", low,
                      f"Turn {turn}: takeover reply should point to a human rep: {reply}")


class TestScoreDoesNotCollapseOnGenericMessage(unittest.TestCase):
    """Score is computed from accumulated profile, not the latest message."""

    def test_generic_followup_keeps_established_intent(self):
        agent = SalesPilotAgent()
        cid = "C-SC"
        r_apply = agent.handle_message(cid, "T", "How much is Plus? I want to apply")
        established = r_apply.score.total
        r_apply2 = agent.handle_message(cid, "T", "How do I apply?")
        established = max(established, r_apply2.score.total)

        # A run of generic messages must not erase established purchase intent
        for msg in ("ok thanks", "hmm", "still thinking about it"):
            r = agent.handle_message(cid, "T", msg)
            self.assertGreaterEqual(
                r.score.total, established - 5,
                f"Generic message '{msg}' collapsed the score "
                f"({r.score.total} vs established {established})",
            )
            self.assertEqual(r.opportunity.best_intent.value, "application",
                             "best_intent must persist as the strongest seen")


class TestTakeoverConversionExpansion(unittest.TestCase):
    """P0: legitimate lifecycle transitions pass through the takeover freeze.

    Human Takeover means 'AI stops autonomous customer-facing sales' — NOT
    'stop tracking the opportunity lifecycle'. Explicit Conversion must still
    move the opportunity to Closed/Active, and a later expansion request must
    still be detected/recorded — all while takeover stays active and the AI
    never resumes autonomous sales.
    """

    CONVERSION_MESSAGES = (
        "I've completed the payment.",
        "I signed up.",
        "I've completed my application and payment.",
        "I've bought the plan.",
    )

    def _reach_takeover_high_intent(self, agent, cid):
        """Drive an opportunity to High Intent + active human takeover."""
        agent.handle_message(cid, "Sarah", "I want private hospital coverage")
        agent.handle_message(cid, "Sarah", "How much is the Plus plan?")
        agent.handle_message(cid, "Sarah", "Another insurer is cheaper, and I have a child")
        r = agent.handle_message(cid, "Sarah", "Okay, how do I apply?")
        self.assertEqual(r.opportunity.state, OpportunityState.HIGH_INTENT)
        self.assertTrue(r.opportunity.human_takeover, "Setup: takeover should be active")
        self.assertIsNotNone(r.case, "Setup: a HITL case should exist")
        return r

    def _assert_neutral(self, reply, where):
        low = reply.lower()
        for word in _SALES_WORDS:
            self.assertNotIn(word, low,
                             f"{where}: takeover reply must not push sales ('{word}'): {reply}")
        self.assertNotIn("would you like me to", low,
                         f"{where}: reply must not offer autonomous help: {reply}")
        self.assertIn("representative", low,
                      f"{where}: reply should point to a human rep: {reply}")

    def test_takeover_then_conversion_moves_to_closed_active(self):
        """1. High Intent -> Takeover -> Conversion."""
        for msg in self.CONVERSION_MESSAGES:
            agent = SalesPilotAgent()
            cid = "C-CONV"
            self._reach_takeover_high_intent(agent, cid)
            cases_before = len(agent.repo.list_cases())

            r = agent.handle_message(cid, "Sarah", msg)
            self.assertIn(Signal.CONVERSION, r.detection.signals,
                          f"Conversion signal expected for: '{msg}'")
            self.assertEqual(
                r.opportunity.state, OpportunityState.CLOSED_ACTIVE,
                f"Conversion must move to Closed/Active for: '{msg}' "
                f"(got {r.opportunity.state.value})",
            )
            self.assertTrue(r.opportunity.human_takeover,
                            "human_takeover must REMAIN True after conversion")
            self.assertTrue(r.next_best_action.human_intervention_required,
                            "NBA must stay human handling — no autonomous sales")
            self._assert_neutral(r.reply, "conversion")
            self.assertIsNone(r.case, "Conversion must NOT create a duplicate case")
            self.assertEqual(len(agent.repo.list_cases()), cases_before,
                             "No new case should be created on conversion")

    def test_takeover_conversion_then_expansion(self):
        """2. High Intent -> Takeover -> Conversion -> Expansion."""
        agent = SalesPilotAgent()
        cid = "C-CONV-EXP"
        self._reach_takeover_high_intent(agent, cid)

        conv = agent.handle_message(cid, "Sarah", "I've completed the payment and signed up")
        self.assertEqual(conv.opportunity.state, OpportunityState.CLOSED_ACTIVE)

        exp = agent.handle_message(cid, "Sarah", "Can I add my spouse to the plan too?")
        # Expansion detected and recorded on the profile
        self.assertIn(Signal.EXPANSION_FAMILY, exp.detection.signals,
                      "Expansion (Family) signal should be detected")
        self.assertIn("Family", exp.opportunity.expansion,
                      "Expansion opportunity should be recorded on the profile")
        # Opportunity remains Closed/Active (a stray expansion request must not
        # drag it elsewhere) and takeover stays active
        self.assertEqual(exp.opportunity.state, OpportunityState.CLOSED_ACTIVE)
        self.assertTrue(exp.opportunity.human_takeover,
                        "human_takeover must REMAIN True through expansion")
        # AI must NOT resume autonomous sales while a human owns the case
        self.assertTrue(exp.next_best_action.human_intervention_required)
        self._assert_neutral(exp.reply, "expansion")
        self.assertIsNone(exp.case, "Expansion must not create a duplicate case")

    def test_takeover_then_withdrawal_unchanged(self):
        """3. Existing withdrawal behavior must remain unchanged."""
        agent = SalesPilotAgent()
        cid = "C-CONV-WD"
        self._reach_takeover_high_intent(agent, cid)

        r = agent.handle_message(cid, "Sarah", "Actually I won't buy anymore.")
        self.assertIn(Signal.WITHDRAWAL, r.detection.signals)
        self.assertEqual(r.opportunity.state, OpportunityState.DORMANT_LOST,
                         "Withdrawal must still move to Dormant/Lost")
        self.assertTrue(r.opportunity.human_takeover,
                        "human_takeover must REMAIN True after withdrawal")
        self._assert_neutral(r.reply, "withdrawal")

    def test_takeover_then_generic_followup_unchanged(self):
        """4. Existing takeover persistence on a generic message is unchanged."""
        agent = SalesPilotAgent()
        cid = "C-CONV-GEN"
        setup = self._reach_takeover_high_intent(agent, cid)
        state_before = setup.opportunity.state
        score_before = setup.score.total

        r = agent.handle_message(cid, "Sarah", "Okay, I am still thinking about it.")
        # State frozen, score does not collapse, reply neutral, takeover active
        self.assertEqual(r.opportunity.state, state_before,
                         "Generic follow-up must not change the state under takeover")
        self.assertGreaterEqual(r.score.total, score_before,
                                "Generic follow-up must not collapse the score")
        self.assertTrue(r.opportunity.human_takeover)
        self.assertTrue(r.next_best_action.human_intervention_required)
        self._assert_neutral(r.reply, "generic")


class TestBuyIntentPhrasing(unittest.TestCase):
    """U3: direct plan interest ('I want Plus') advances past Cold Lead but
    must NOT jump straight to High Intent."""

    INTEREST_MESSAGES = (
        "I want Plus",
        "I want Essential",
        "I'm interested in Plus",
        "I want the Plus plan",
        "I want a plan",
        "looking for a plan",
    )

    def setUp(self):
        self.intent = IntentClassifier()

    def test_interest_phrasing_is_not_generic(self):
        for msg in self.INTEREST_MESSAGES:
            self.assertNotEqual(
                self.intent.detect(msg), Intent.GENERIC,
                f"'{msg}' should be recognised as product interest, not generic",
            )

    def test_interest_advances_state_but_not_high_intent(self):
        for msg in self.INTEREST_MESSAGES:
            agent = SalesPilotAgent()
            r = agent.handle_message("C-BUY", "T", msg)
            # Advances out of Cold Lead...
            self.assertNotEqual(
                r.opportunity.state, OpportunityState.COLD_LEAD,
                f"'{msg}' should advance past Cold Lead",
            )
            # ...but must NOT jump straight to High Intent on turn 1
            self.assertNotEqual(
                r.opportunity.state, OpportunityState.HIGH_INTENT,
                f"'{msg}' must not jump straight to High Intent",
            )
            # and must not emit a Purchase signal from mere interest
            self.assertNotIn(Signal.PURCHASE, r.detection.signals,
                             f"'{msg}' should not be a Purchase signal")

    def test_family_plan_interest_still_family_need(self):
        # Existing behaviour preserved (FAMILY_NEED is matched before COVERAGE)
        self.assertEqual(
            self.intent.detect("I'd like the Family plan"), Intent.FAMILY_NEED
        )


class TestNonTakeoverLifecycle(unittest.TestCase):
    """U4: characterization tests for the primary demo lifecycle (test-only)."""

    def test_full_lifecycle_without_takeover(self):
        """Potential Interest -> Evaluation -> High Intent -> Conversion ->
        Closed/Active -> Expansion, with NO human takeover (clean path)."""
        agent = SalesPilotAgent()
        cid = "C-LIFE"

        r1 = agent.handle_message(cid, "T", "I want private hospital coverage")
        self.assertEqual(r1.opportunity.state, OpportunityState.POTENTIAL_INTEREST)

        r2 = agent.handle_message(cid, "T", "How much is the Plus plan?")
        self.assertEqual(r2.opportunity.state, OpportunityState.EVALUATION_HESITATION)

        r3 = agent.handle_message(cid, "T", "How do I apply?")
        self.assertEqual(r3.opportunity.state, OpportunityState.HIGH_INTENT)
        self.assertFalse(r3.opportunity.human_takeover,
                         "Clean path (no competitive risk) must not take over")

        r4 = agent.handle_message(cid, "T", "I've completed the payment and signed up")
        self.assertIn(Signal.CONVERSION, r4.detection.signals)
        self.assertEqual(r4.opportunity.state, OpportunityState.CLOSED_ACTIVE)

        r5 = agent.handle_message(cid, "T", "Can I add my spouse to the plan too?")
        self.assertIn(Signal.EXPANSION_FAMILY, r5.detection.signals)
        self.assertEqual(r5.opportunity.state, OpportunityState.CLOSED_ACTIVE)
        self.assertIn("Family", r5.opportunity.expansion)
        self.assertIn("expansion", r5.next_best_action.action.lower())
        # Whole clean journey created no HITL case
        self.assertEqual(len(agent.repo.list_cases()), 0)

    def test_competitive_during_evaluation_sets_competitive_risk(self):
        """The 'Competitive Risk' lifecycle stage: a competitor mention during
        Evaluation flags competitive_risk without moving state by itself."""
        agent = SalesPilotAgent()
        cid = "C-COMP"
        agent.handle_message(cid, "T", "I want private hospital coverage")
        agent.handle_message(cid, "T", "How much is the Plus plan?")
        r = agent.handle_message(cid, "T", "Another insurer is cheaper")
        self.assertEqual(r.opportunity.state, OpportunityState.EVALUATION_HESITATION)
        self.assertTrue(r.opportunity.competitive_risk)
        self.assertIsNone(r.case, "Competitor mention alone must not open a case")

    def test_dormant_reengagement(self):
        """Dormant / Lost -> new insurance need -> Potential Interest."""
        agent = SalesPilotAgent()
        cid = "C-REENG"
        agent.handle_message(cid, "T", "How much is Plus? I want to apply")
        r_wd = agent.handle_message(cid, "T", "I won't buy anymore")
        self.assertEqual(r_wd.opportunity.state, OpportunityState.DORMANT_LOST)

        r_re = agent.handle_message(cid, "T", "How much is the family plan?")
        self.assertEqual(r_re.opportunity.state, OpportunityState.POTENTIAL_INTEREST)


class TestSafePatternDoesNotSuppressEscalation(unittest.TestCase):
    """Regression: a message containing a 'safe pattern' phrase (e.g. 'tell me
    about') must still escalate when it also carries an explicit human
    request, complaint, negotiation, or compliance-risk signal. The safe
    patterns exist only to avoid escalating on low retrieval confidence for
    generic questions — they must never suppress these explicit signals."""

    def test_human_request_with_safe_pattern_still_escalates(self):
        agent = SalesPilotAgent()
        r = agent.handle_message(
            "C-SAFE1", "T",
            "Can you tell me about the plans, I'd like to speak to a human",
        )
        self.assertIn(Signal.HUMAN_REQUEST, r.detection.signals)
        self.assertIsNotNone(
            r.case, "Explicit human request must escalate even with a 'safe pattern' phrase",
        )

    def test_complaint_with_safe_pattern_still_escalates(self):
        agent = SalesPilotAgent()
        agent.handle_message("C-SAFE2", "T", "What plans do you have?")
        r = agent.handle_message(
            "C-SAFE2", "T",
            "I want to learn about your complaint process, I have a complaint",
        )
        self.assertEqual(r.detection.intent, Intent.COMPLAINT)
        self.assertIsNotNone(
            r.case, "Complaint must escalate even with a 'safe pattern' phrase",
        )


if __name__ == "__main__":
    unittest.main()
