# -*- coding: utf-8 -*-
"""End-to-end tests for the SalesPilot minimal scaffold (stdlib unittest).

Run:
    cd SalesPilot
    py -3 -m unittest discover -s tests -v
"""
import sys
import unittest
from pathlib import Path

# Make the root-level salespilot package importable when tests are run directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from salespilot.agent import SalesPilotAgent
from salespilot.detection import IntentClassifier, ProductClassifier, SignalDetector
from salespilot.knowledge import KnowledgeRetriever
from salespilot.models import Intent, OpportunityState, Product, Signal


class TestClassifiers(unittest.TestCase):
    def setUp(self):
        self.intent = IntentClassifier()
        self.product = ProductClassifier()
        self.signals = SignalDetector()

    def test_intent_detection(self):
        self.assertEqual(self.intent.detect("How much does Plus cost?"), Intent.PRICE)
        self.assertEqual(
            self.intent.detect("How do I apply for the plan?"),
            Intent.APPLICATION,
        )
        self.assertEqual(
            self.intent.detect("I have a pre-existing heart condition"),
            Intent.UNDERWRITING,
        )

    def test_product_detection(self):
        self.assertEqual(
            self.product.detect("I want private hospital coverage"), Product.PLUS
        )
        self.assertEqual(
            self.product.detect("How much does CareSure Plus cost?"), Product.PLUS
        )
        self.assertEqual(
            self.product.detect("We have 120 employees"), Product.CORPORATE
        )

    def test_signal_detection(self):
        det = self.signals.detect(
            "Another insurer is cheaper, let me think",
            Intent.COMPARISON,
            Product.PLUS,
        )
        self.assertIn(Signal.COMPETITIVE, det.signals)
        self.assertIn(Signal.HESITATION, det.signals)


class TestKnowledgeRetrieval(unittest.TestCase):
    def setUp(self):
        self.retriever = KnowledgeRetriever()

    def test_grounded_price_fact(self):
        result = self.retriever.retrieve(
            "How much is the premium?", Product.PLUS, Intent.PRICE
        )
        self.assertGreaterEqual(result.confidence, 0.5)
        joined = "\n".join(result.facts)
        self.assertIn("S$1,500", joined)  # Comes from the KB; never invented

    def test_confidence_when_intent_routes_to_authoritative_field(self):
        # Intent routed to an authoritative KB field (premium) is trustworthy
        result = self.retriever.retrieve(
            "How much is the premium?", Product.PLUS, Intent.PRICE
        )
        self.assertGreaterEqual(result.confidence, 0.8)


class TestAgentWorkflow(unittest.TestCase):
    def setUp(self):
        self.agent = SalesPilotAgent()

    def _say(self, text, customer_id="C-T", name="Tester"):
        return self.agent.handle_message(customer_id, name, text)

    def test_state_progression_and_escalation(self):
        # Cold lead -> potential interest
        r1 = self._say("Hi, I'm interested in private hospital insurance")
        self.assertEqual(r1.opportunity.state, OpportunityState.POTENTIAL_INTEREST)

        # Evaluating a concrete price -> evaluation & hesitation
        r2 = self._say("How much does CareSure Plus cost?")
        self.assertEqual(
            r2.opportunity.state, OpportunityState.EVALUATION_HESITATION
        )

        # Competitor + strong purchase signal -> high intent + human case
        r3 = self._say("Another insurer is cheaper. How do I apply?")
        self.assertEqual(r3.opportunity.state, OpportunityState.HIGH_INTENT)
        self.assertIsNotNone(r3.case)
        self.assertIn("competitive", r3.case.reason.lower())
        self.assertTrue(r3.opportunity.competitive_risk)

    def test_compliance_escalation(self):
        self._say("Tell me about the Plus plan")
        result = self._say(
            "I have diabetes, will it be covered? Can I get underwriting?"
        )
        self.assertIsNotNone(result.case)
        self.assertIn("underwriting", result.case.reason.lower())

    def test_corporate_quote_escalation(self):
        result = self._say(
            "We have 120 employees and want a corporate quotation, how do we sign up?",
            customer_id="C-CO",
            name="ABC Pte Ltd",
        )
        self.assertEqual(result.opportunity.product, Product.CORPORATE)
        self.assertIsNotNone(result.case)

    def test_reply_is_grounded_and_nonempty(self):
        result = self._say("What does the Essential plan cover?")
        self.assertTrue(result.reply.strip())
        self.assertIn("B1", result.reply)  # Knowledge-base fact

    def test_low_retrieval_confidence_escalates(self):
        """When a future vector retriever reports low confidence, HITL must escalate."""
        from salespilot.engine import HITLManager
        from salespilot.models import (
            Detection,
            Opportunity,
            RetrievalResult,
        )

        opp = Opportunity(id="C-X", customer_name="X", product=Product.PLUS)
        det = Detection(intent=Intent.PRICE, product=Product.PLUS)
        retrieval = RetrievalResult(confidence=0.3, product=Product.PLUS)
        reason = HITLManager().evaluate(opp, det, retrieval, "unusual question")
        self.assertIsNotNone(reason)
        self.assertIn("confidence", reason.lower())

    def test_demo_script_runs_end_to_end(self):
        from salespilot.demo import SCRIPT

        agent = SalesPilotAgent()
        for customer_id, name, messages in SCRIPT:
            last = None
            for text in messages:
                last = agent.handle_message(customer_id, name, text)
            self.assertIsNotNone(last)
            self.assertTrue(last.reply.strip())
        # Dashboard rendering must not fail and must contain the title
        from salespilot.dashboard import render_dashboard

        dashboard = render_dashboard(agent.repo)
        self.assertIn("SALES DASHBOARD", dashboard)


if __name__ == "__main__":
    unittest.main()
