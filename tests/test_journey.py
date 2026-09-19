# -*- coding: utf-8 -*-
"""Journey test: verify state, signals, score, priority and NBA evolve across
a single 4-message conversation using conversation history.

Message 1: "I want to learn about health insurance."
  → Potential Interest, Low/Medium score, Nurture

Message 2: "How much is the Plus plan?"
  → Evaluation & Hesitation, score increases, product = Plus

Message 3: "Another insurer is cheaper, but I have a child."
  → Evaluation & Hesitation, Competitive + Hesitation + Expansion signals,
    Competitive Risk = True, Expansion = Family, score increases

Message 4: "Okay, how do I apply?"
  → High Intent, score >= 80, Priority = High, NBA = Take Over / Contact Sales
"""
import unittest

from salespilot.agent import SalesPilotAgent


class TestConversationJourney(unittest.TestCase):
    def setUp(self):
        self.agent = SalesPilotAgent()

    def test_four_message_journey(self):
        cid = "C-JOURNEY-001"
        cname = "Journey Customer"

        # --- Message 1 ---
        r1 = self.agent.handle_message(cid, cname,
                                       "I want to learn about health insurance.")
        self.assertEqual(
            r1.opportunity.state.value, "Potential Interest",
            f"Msg1 state should be Potential Interest, got {r1.opportunity.state.value}"
        )
        self.assertLessEqual(r1.score.total, 49,
                             f"Msg1 score should be Low (<50), got {r1.score.total}")
        self.assertEqual(r1.score.priority.value, "LOW")
        # Nurture: reply should be informative/welcoming
        self.assertTrue(len(r1.reply) > 20, "Msg1 reply should not be empty")
        self.assertTrue(
            r1.next_best_action.human_intervention_required is False,
            "Msg1 should not require human intervention"
        )

        # --- Message 2 ---
        r2 = self.agent.handle_message(cid, cname,
                                       "How much is the Plus plan?")
        self.assertEqual(
            r2.opportunity.state.value, "Evaluation & Hesitation",
            f"Msg2 state should be Evaluation & Hesitation, got {r2.opportunity.state.value}"
        )
        self.assertEqual(
            r2.opportunity.product.value, "plus",
            f"Msg2 product should be Plus, got {r2.opportunity.product.value}"
        )
        self.assertGreater(
            r2.score.total, r1.score.total,
            f"Msg2 score ({r2.score.total}) should > Msg1 score ({r1.score.total})"
        )
        self.assertEqual(r2.detection.intent.value, "price")

        # --- Message 3 ---
        r3 = self.agent.handle_message(
            cid, cname,
            "Another insurer is cheaper, but I have a child."
        )
        self.assertEqual(
            r3.opportunity.state.value, "Evaluation & Hesitation",
            f"Msg3 state should remain Evaluation & Hesitation, "
            f"got {r3.opportunity.state.value}"
        )
        # Signals: Competitive + Hesitation + Expansion (Family)
        signal_values = {s.value for s in r3.opportunity.signals}
        self.assertIn("Competitive", signal_values,
                      "Msg3 should have Competitive signal")
        self.assertIn("Hesitation", signal_values,
                      "Msg3 should have Hesitation signal")
        self.assertIn("Expansion: Family", signal_values,
                      "Msg3 should have Expansion: Family signal")

        # Flags
        self.assertTrue(r3.opportunity.competitive_risk,
                        "Msg3 should set competitive_risk = True")
        self.assertIn("Family", r3.opportunity.expansion,
                      "Msg3 should add Family to expansion list")

        # Score increases
        self.assertGreater(
            r3.score.total, r2.score.total,
            f"Msg3 score ({r3.score.total}) should > Msg2 score ({r2.score.total})"
        )

        # --- Message 4 ---
        r4 = self.agent.handle_message(cid, cname,
                                       "Okay, how do I apply?")
        self.assertEqual(
            r4.opportunity.state.value, "High Intent",
            f"Msg4 state should be High Intent, got {r4.opportunity.state.value}"
        )
        self.assertGreaterEqual(
            r4.score.total, 80,
            f"Msg4 score should be >= 80, got {r4.score.total}"
        )
        self.assertEqual(
            r4.score.priority.value, "HIGH",
            f"Msg4 priority should be HIGH, got {r4.score.priority.value}"
        )
        # NBA should indicate take-over / contact sales / human sales intervention
        nba_text = r4.next_best_action.action.lower()
        self.assertTrue(
            "take over" in nba_text or "take-over" in nba_text
            or "contact sales" in nba_text or "contact the customer" in nba_text
            or "human sales intervention" in nba_text or "sales intervention" in nba_text,
            f"Msg4 NBA should mention take-over/contact-sales/sales-intervention, got: {r4.next_best_action.action}"
        )
        self.assertTrue(
            r4.next_best_action.human_intervention_required,
            "Msg4 should require human intervention"
        )

        # Score history should have 4 entries
        self.assertEqual(
            len(r4.opportunity.score_history), 4,
            f"Score history should have 4 entries, got {len(r4.opportunity.score_history)}"
        )

        # State history should have transitions recorded
        self.assertGreaterEqual(
            len(r4.opportunity.state_history), 2,
            f"State history should have >= 2 transitions, "
            f"got {len(r4.opportunity.state_history)}"
        )

    def test_scores_monotonically_increasing(self):
        """Verify that the score increases across the 4-message journey."""
        cid = "C-JOURNEY-002"
        cname = "Score Test Customer"
        messages = [
            "I want to learn about health insurance.",
            "How much is the Plus plan?",
            "Another insurer is cheaper, but I have a child.",
            "Okay, how do I apply?",
        ]
        scores = []
        for msg in messages:
            r = self.agent.handle_message(cid, cname, msg)
            scores.append(r.score.total)
        for i in range(1, len(scores)):
            self.assertGreater(
                scores[i], scores[i - 1],
                f"Score at msg {i + 1} ({scores[i]}) should > "
                f"score at msg {i} ({scores[i - 1]})"
            )


if __name__ == "__main__":
    unittest.main()
