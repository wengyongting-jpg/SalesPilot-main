# -*- coding: utf-8 -*-
"""Acceptance test: 5-message conversation with withdrawal.

Verifies that state, signals, score, priority, and NBA evolve correctly
across a single conversation, and that withdrawal properly overrides
previous positive signals.
"""
import unittest

from salespilot.agent import SalesPilotAgent
from salespilot.models import OpportunityState, Priority, Signal


class TestWithdrawalJourney(unittest.TestCase):
    """Test the exact 5-message conversation from the spec."""

    def setUp(self):
        self.agent = SalesPilotAgent()
        self.cid = "C-ACCEPT"
        self.name = "Sarah"

    def test_5_message_journey(self):
        # Message 1: "Can you introduce your products?"
        r1 = self.agent.handle_message(self.cid, self.name, "Can you introduce your products?")
        self.assertEqual(r1.opportunity.state, OpportunityState.POTENTIAL_INTEREST)
        self.assertFalse(r1.next_best_action.human_intervention_required,
                         "Generic product enquiry must NOT trigger HITL")
        self.assertIn("nurtur", (r1.next_best_action.action + r1.reply).lower())
        score1 = r1.score.total
        self.assertLess(score1, 50, f"Score should be low for generic enquiry, got {score1}")

        # Message 2: "How much is Plus?"
        r2 = self.agent.handle_message(self.cid, self.name, "How much is the Plus plan?")
        self.assertEqual(r2.opportunity.state, OpportunityState.EVALUATION_HESITATION)
        self.assertFalse(r2.next_best_action.human_intervention_required,
                         "Price enquiry must NOT trigger HITL")
        self.assertTrue(
            Signal.PURCHASE in r2.detection.signals or
            r2.opportunity.product.value == "plus",
            "Product should be detected as Plus"
        )
        score2 = r2.score.total
        self.assertGreater(score2, score1, "Score should increase after product evaluation")

        # Message 3: "Another insurer is cheaper and I have a child."
        r3 = self.agent.handle_message(self.cid, self.name, "Another insurer is cheaper and I have a child.")
        self.assertEqual(r3.opportunity.state, OpportunityState.EVALUATION_HESITATION)
        self.assertTrue(r3.opportunity.competitive_risk, "Competitive risk should be flagged")
        self.assertIn("Family", r3.opportunity.expansion, "Family expansion should be detected")
        score3 = r3.score.total
        self.assertGreater(score3, score2, "Score should increase with more signals")

        # Message 4: "How do I apply?"
        r4 = self.agent.handle_message(self.cid, self.name, "How do I apply?")
        self.assertEqual(r4.opportunity.state, OpportunityState.HIGH_INTENT,
                         f"Expected High Intent, got {r4.opportunity.state}")
        score4 = r4.score.total
        self.assertGreaterEqual(score4, score3, "Score should increase significantly")
        self.assertGreater(score4, 60, f"Score should be high after apply, got {score4}")

        # Message 5: "Actually I won't buy anymore."
        r5 = self.agent.handle_message(self.cid, self.name, "Actually I won't buy anymore.")
        self.assertEqual(r5.opportunity.state, OpportunityState.DORMANT_LOST,
                         f"Expected Dormant/Lost after withdrawal, got {r5.opportunity.state}")
        score5 = r5.score.total
        self.assertLess(score5, 50, f"Score should drop below 50 after withdrawal, got {score5}")
        self.assertEqual(r5.score.priority, Priority.LOW,
                         "Priority should be LOW after withdrawal")
        # NOTE (P0-3): a human takeover already became active at message 4
        # (High Intent + competitive risk). Once takeover is active it MUST
        # persist, so the next-best-action stays "human handling" here. This
        # is NOT the withdrawal itself triggering HITL — withdrawal on its own
        # never escalates (see test_score_direction and the P0 regression
        # suite). The key withdrawal guarantees below still hold:
        self.assertTrue(r5.next_best_action.human_intervention_required,
                        "Human takeover from msg4 must persist through msg5 (P0-3)")
        self.assertIsNone(r5.case, "No new HITL case should be created for withdrawal")

        # Verify signal history is preserved
        self.assertIn(Signal.WITHDRAWAL, r5.opportunity.signals,
                      "Withdrawal should be the active signal")
        self.assertIn(Signal.PURCHASE, r5.opportunity.signal_history,
                      "Purchase should be in signal history")
        self.assertIn(Signal.COMPETITIVE, r5.opportunity.signal_history,
                      "Competitive should be in signal history")

        # Verify exactly 1 HITL case (created at msg4, no new case at msg5)
        cases = self.agent.repo.list_cases()
        self.assertEqual(len(cases), 1,
                         "Exactly 1 HITL case should exist (from msg4 high-intent+competitive)")
        # Verify msg5 did not create a NEW case
        self.assertIsNone(r5.case, "Msg5 (withdrawal) must NOT create a new HITL case")

    def test_no_hitl_for_safe_messages(self):
        """Messages that should NOT trigger HITL."""
        safe_messages = [
            "Can you introduce your product?",
            "What plans do you have?",
            "How much is Plus?",
            "What does Essential cover?",
            "What is the waiting period?",
            "I just need some basic information.",
        ]
        for msg in safe_messages:
            agent = SalesPilotAgent()
            r = agent.handle_message("C-SAFE", "Test", msg)
            self.assertIsNone(r.case, f"HITL should not trigger for: '{msg}'")
            self.assertFalse(r.next_best_action.human_intervention_required,
                             f"HITL flag should be False for: '{msg}'")

    def test_hitl_for_restricted_cases(self):
        """Messages that SHOULD trigger HITL."""
        restricted_messages = [
            "I have a pre-existing medical condition, can I get covered?",
            "My claim was denied, I want to dispute it",
            "Can you give me a custom quotation for my company?",
            "I want to speak to a human agent",
        ]
        for msg in restricted_messages:
            agent = SalesPilotAgent()
            r = agent.handle_message("C-RESTR", "Test", msg)
            self.assertIsNotNone(r.case, f"HITL should trigger for: '{msg}'")

    def test_one_case_per_opportunity(self):
        """Multiple messages that trigger HITL should only create ONE case."""
        agent = SalesPilotAgent()
        cid = "C-ONE-CASE"
        # First message triggers HITL
        r1 = agent.handle_message(cid, "Test", "I have a pre-existing condition, can I get covered?")
        self.assertIsNotNone(r1.case, "First restricted message should create a case")
        case1_id = r1.case.id

        # Second message also triggers HITL — should update existing, not create new
        r2 = agent.handle_message(cid, "Test", "I also want to dispute my claim")
        cases = agent.repo.list_cases()
        open_cases = [c for c in cases if c.opportunity_id == cid and c.status.value != "Closed"]
        self.assertEqual(len(open_cases), 1,
                         "Should have exactly one active case, not create a new one")

    def test_score_direction(self):
        """Verify score moves in the right direction for each message type."""
        agent = SalesPilotAgent()
        cid = "C-SCORE-DIR"
        r1 = agent.handle_message(cid, "T", "How much is the Plus plan?")
        s1 = r1.score.total
        r2 = agent.handle_message(cid, "T", "Another insurer is cheaper, but I have a child.")
        s2 = r2.score.total
        r3 = agent.handle_message(cid, "T", "How do I apply?")
        s3 = r3.score.total
        r4 = agent.handle_message(cid, "T", "I won't buy anymore.")
        s4 = r4.score.total

        self.assertGreater(s2, s1, "More signals → higher score")
        self.assertGreater(s3, s2, "Apply → higher score")
        self.assertLess(s4, s3, "Withdrawal → much lower score")
        self.assertLess(s4, 50, "Withdrawal score should be Low priority range")


if __name__ == "__main__":
    unittest.main()
