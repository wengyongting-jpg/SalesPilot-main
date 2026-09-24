# -*- coding: utf-8 -*-
"""P1: `domain/` is the single source of truth for every wire string.

The literal lists below are transcribed independently from
`docs/v0.0/api/interface-v1.md` §4.3 and §1.2. That duplication is the point: if an
enum is renamed, reordered or extended, the comparison fails here rather than
reaching a frontend that has no build step and no type checking to catch it.

This is the `U`-series contract idea from the frozen build, moved to the layer
that actually defines the strings.
"""
from __future__ import annotations

import unittest
from pathlib import Path

DOMAIN = Path(__file__).resolve().parent.parent / "domain"

# --- transcribed from docs/v0.0/api/interface-v1.md §4.3 -----------------------

STATES = [
    "Cold Lead",
    "Potential Interest",
    "Evaluation & Hesitation",
    "High Intent",
    "Closed / Active Customer",
    "Dormant / Lost",
]
PRIORITIES = ["HIGH", "MEDIUM", "LOW"]
PRODUCTS = ["essential", "family", "plus", "corporate", "unknown"]
SIGNALS = [
    "Purchase",
    "Purchase Preparation",
    "Hesitation",
    "Competitive",
    "Expansion: Family",
    "Expansion: Corporate",
    "Human Request",
    "Compliance Risk",
    "Negotiation",
    "Conversion",
    "Withdrawal",
]
CASE_STATUSES = ["Open", "Taken Over", "Closed"]

# --- transcribed from docs/v0.0/api/interface-v1.md §1.2 and §5.7 -------------

ROLES = ["customer", "business"]
AUTHORS = ["ai", "human", "system"]
GENERATIONS = ["llm", "template", "human"]


class TestWireEnumContracts(unittest.TestCase):
    """U5-U8 equivalent: the exact serialised strings, in order."""

    def test_opportunity_states(self):
        from backend.domain.enums import OpportunityState

        self.assertEqual([s.value for s in OpportunityState], STATES)

    def test_priorities_are_uppercase(self):
        from backend.domain.enums import Priority

        self.assertEqual([p.value for p in Priority], PRIORITIES)

    def test_products_are_lowercase(self):
        from backend.domain.enums import Product

        self.assertEqual([p.value for p in Product], PRODUCTS)

    def test_signals_keep_the_colon_space_form(self):
        from backend.domain.enums import Signal

        self.assertEqual([s.value for s in Signal], SIGNALS)

    def test_case_statuses_are_title_case(self):
        from backend.domain.enums import CaseStatus

        self.assertEqual([c.value for c in CaseStatus], CASE_STATUSES)

    def test_the_three_message_axes(self):
        from backend.domain.enums import Generation, MessageAuthor, MessageRole

        self.assertEqual([r.value for r in MessageRole], ROLES)
        self.assertEqual([a.value for a in MessageAuthor], AUTHORS)
        self.assertEqual([g.value for g in Generation], GENERATIONS)


class TestRoleRename(unittest.TestCase):
    """interface-v1 §5.8: `role: "agent"` is gone, with no transitional alias."""

    def test_role_has_no_agent_value(self):
        from backend.domain.enums import MessageRole

        self.assertNotIn("agent", [r.value for r in MessageRole])

    def test_role_is_a_closed_set_of_two(self):
        from backend.domain.enums import MessageRole

        self.assertEqual(2, len(list(MessageRole)))

    def test_no_live_agent_string_literal_survives_in_domain(self):
        """A deprecated member or a serialiser special case would reopen the set.

        Scans string *literals* via the AST rather than raw text, so the prose in
        `enums.py` that explains why the rename happened is not mistaken for a
        surviving alias. Comments never enter the AST, and a docstring is one
        constant holding the whole paragraph rather than the bare word.
        """
        import ast

        offenders = []
        for path in DOMAIN.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and node.value == "agent"
                ):
                    offenders.append(f"{path.name}:{node.lineno}")
        self.assertEqual(
            [], offenders,
            "a live \"agent\" literal remains in domain/: " + ", ".join(offenders),
        )


class TestIntentCoversWhatEscalationNeeds(unittest.TestCase):
    """Guards the specific defect that motivated the rebuild.

    In the frozen build the extraction prompt offered the model
    `"medical_question"` while the domain defined `"underwriting"`. The mismatch
    made `Intent.UNDERWRITING` unreachable in LLM mode, which silently disabled
    the medical/underwriting escalation trigger.
    """

    def test_underwriting_exists(self):
        from backend.domain.enums import Intent

        self.assertEqual("underwriting", Intent.UNDERWRITING.value)

    def test_medical_question_is_not_a_synonym(self):
        from backend.domain.enums import Intent

        self.assertNotIn("medical_question", [i.value for i in Intent])

    def test_every_intent_the_escalation_rules_read_is_defined(self):
        from backend.domain.enums import Intent

        for name in ("GENERIC", "PRICE", "COVERAGE", "ELIGIBILITY", "CLAIMS",
                     "WAITING_PERIOD", "PAYMENT", "APPLICATION", "COMPARISON",
                     "FAMILY_NEED", "CORPORATE_NEED", "UNDERWRITING",
                     "HUMAN_REQUEST", "COMPLAINT"):
            self.assertTrue(hasattr(Intent, name), f"Intent.{name} missing")


class TestMessageAxes(unittest.TestCase):
    """interface-v1 §1.2 and §5.7: three orthogonal axes, five valid states."""

    def test_the_five_documented_combinations_are_accepted(self):
        from backend.domain.message import Message

        cases = [
            Message.from_customer("hello"),
            Message.from_ai("hi", generation="llm"),
            Message.from_ai("hi", generation="template"),
            Message.from_human("hi", rep_name="Alex"),
            Message.from_system("A representative is taking over."),
        ]
        observed = [(m.role.value, m.author_value, m.generation_value) for m in cases]
        self.assertEqual(
            [
                ("customer", None, None),
                ("business", "ai", "llm"),
                ("business", "ai", "template"),
                ("business", "human", "human"),
                ("business", "system", "template"),
            ],
            observed,
        )

    def test_a_customer_message_carries_neither_author_nor_generation(self):
        from backend.domain.message import Message

        message = Message.from_customer("hello", client_message_id="k1")
        self.assertIsNone(message.author)
        self.assertIsNone(message.generation)
        self.assertEqual("k1", message.client_message_id)

    def test_a_business_message_always_states_how_it_was_produced(self):
        """§5.7: offline replies must be distinguishable from model replies."""
        from backend.domain.enums import Generation, MessageAuthor, MessageRole
        from backend.domain.message import Message

        with self.assertRaises(ValueError):
            Message(role=MessageRole.BUSINESS, text="x", author=MessageAuthor.AI)
        with self.assertRaises(ValueError):
            Message(role=MessageRole.BUSINESS, text="x", generation=Generation.LLM)

    def test_undocumented_combinations_are_rejected(self):
        from backend.domain.enums import Generation, MessageAuthor, MessageRole
        from backend.domain.message import Message

        rejected = [
            # A human did not produce their words with a template or a model.
            dict(author=MessageAuthor.HUMAN, generation=Generation.LLM),
            dict(author=MessageAuthor.HUMAN, generation=Generation.TEMPLATE),
            # "human" generation only makes sense for a human author.
            dict(author=MessageAuthor.AI, generation=Generation.HUMAN),
            dict(author=MessageAuthor.SYSTEM, generation=Generation.HUMAN),
            # A deterministic system notice is never model-generated.
            dict(author=MessageAuthor.SYSTEM, generation=Generation.LLM),
        ]
        for combination in rejected:
            with self.subTest(**combination):
                with self.assertRaises(ValueError):
                    Message(role=MessageRole.BUSINESS, text="x", **combination)

    def test_a_customer_message_may_not_claim_an_author(self):
        from backend.domain.enums import MessageAuthor, MessageRole
        from backend.domain.message import Message

        with self.assertRaises(ValueError):
            Message(
                role=MessageRole.CUSTOMER, text="x", author=MessageAuthor.AI,
            )

    def test_rep_name_belongs_to_human_messages_only(self):
        from backend.domain.message import Message

        self.assertEqual("Alex", Message.from_human("hi", rep_name="Alex").rep_name)
        self.assertIsNone(Message.from_ai("hi", generation="llm").rep_name)
        with self.assertRaises(ValueError):
            Message.from_ai("hi", generation="llm", rep_name="Alex")


class TestMessageIdentity(unittest.TestCase):
    """interface-v1 §5 item 5: a stable id per message."""

    def test_every_message_gets_a_unique_id(self):
        from backend.domain.message import Message

        ids = {Message.from_customer("x").id for _ in range(50)}
        self.assertEqual(50, len(ids))

    def test_an_explicit_id_is_preserved(self):
        from backend.domain.message import Message

        self.assertEqual("m-1", Message.from_customer("x", id="m-1").id)


class TestCounterNaming(unittest.TestCase):
    """interface-v1 §1.1: `turns` is deprecated in favour of a truthful name."""

    def test_customer_message_count_is_the_field(self):
        from backend.domain.opportunity import Opportunity

        opportunity = Opportunity(id="C-1", customer_name="Sam")
        self.assertEqual(0, opportunity.customer_message_count)
        opportunity.customer_message_count += 1
        self.assertEqual(1, opportunity.customer_message_count)

    def test_turns_is_a_read_only_alias(self):
        """Kept for the wire, unassignable in code, so the truthful name is the
        only one that can be used internally."""
        from backend.domain.opportunity import Opportunity

        opportunity = Opportunity(id="C-1", customer_name="Sam")
        opportunity.customer_message_count = 3
        self.assertEqual(3, opportunity.turns)
        with self.assertRaises(AttributeError):
            opportunity.turns = 4

    def test_turns_is_not_a_dataclass_field(self):
        import dataclasses

        from backend.domain.opportunity import Opportunity

        names = {f.name for f in dataclasses.fields(Opportunity)}
        self.assertIn("customer_message_count", names)
        self.assertNotIn("turns", names)


if __name__ == "__main__":
    unittest.main()
