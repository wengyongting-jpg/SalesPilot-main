# -*- coding: utf-8 -*-
"""P3: the tool surface — read-only lookups, and the one proposal tool."""
from __future__ import annotations

import unittest

from backend.agent.tools import (
    compare_products,
    get_conversation_summary,
    list_products,
    lookup_product_fact,
    request_human_handoff,
)
from backend.domain.detection import HandoffProposal
from backend.domain.enums import Product
from backend.domain.message import Message


class TestKnowledgeTools(unittest.TestCase):
    def test_lookup_product_fact_returns_an_approved_fact(self):
        fact = lookup_product_fact(Product.ESSENTIAL, "premium")
        self.assertIn("CareSure Essential", fact)

    def test_lookup_product_fact_reports_a_missing_field_rather_than_guessing(self):
        fact = lookup_product_fact(Product.ESSENTIAL, "not_a_real_field")
        self.assertIn("No approved fact found", fact)

    def test_compare_products_returns_both_sides(self):
        result = compare_products(Product.PLUS, Product.FAMILY, "waiting_period")
        self.assertIn("CareSure Plus", result)
        self.assertIn("CareSure Family", result)

    def test_list_products_lists_every_product(self):
        listing = list_products().lower()
        for product in (Product.ESSENTIAL, Product.FAMILY, Product.PLUS, Product.CORPORATE):
            self.assertIn(product.value.lower(), listing)


class TestConversationSummaryToolIsTextOnly(unittest.TestCase):
    def test_empty_history_says_so(self):
        self.assertIn("No prior messages", get_conversation_summary([]))

    def test_summary_only_ever_contains_message_text(self):
        history = [
            Message.from_customer("How much is Plus?"),
            Message.from_ai("It starts from S$900/year.", generation="template"),
        ]
        summary = get_conversation_summary(history)
        self.assertIn("How much is Plus?", summary)
        self.assertIn("S$900/year", summary)
        # No internal vocabulary should ever be reachable here since this
        # function only ever sees `Message.text`.
        self.assertNotIn("Priority", summary)
        self.assertNotIn("Cold Lead", summary)


class TestHandoffToolIsAProposalOnly(unittest.TestCase):
    def test_returns_a_handoff_proposal_with_the_given_reason(self):
        proposal = request_human_handoff(reason="Explicit request for a person")
        self.assertIsInstance(proposal, HandoffProposal)
        self.assertTrue(proposal.requested)
        self.assertEqual(proposal.reason, "Explicit request for a person")
