# -*- coding: utf-8 -*-
"""Intent classifier — what the customer is asking about.

Uses keyword matching with conversation-history context resolution:
if the current message is ambiguous (e.g. "yes", "how much", "ok"), the
classifier looks at recent messages to infer the most likely intent.

Match order is priority: high-risk / strong intents come first.
"""
from __future__ import annotations

from ..models import Intent, Message

# (intent, trigger phrases) — matched as lowercase substrings
_INTENT_PHRASES: list[tuple[Intent, tuple[str, ...]]] = [
    (Intent.HUMAN_REQUEST, (
        "speak to someone", "speak to a person", "talk to a human", "human agent",
        "real person", "call me", "sales rep", "sales representative",
        "someone contact me", "consultant to contact",
        "speak to a human", "talk to a person", "speak to an agent",
        "talk to an agent", "to a human", "with a human", "speak to a real",
        "speak with someone", "talk to someone", "human being",
    )),
    (Intent.COMPLAINT, (
        "complaint", "complain", "not happy", "unhappy", "frustrated",
        "want to cancel", "cancel my policy", "dispute", "denied claim",
        "claim was rejected",
    )),
    (Intent.UNDERWRITING, (
        "pre-existing", "pre existing", "underwrit", "medical history",
        "diagnosed", "my condition", "chronic", "asthma", "diabetes",
    )),
    (Intent.APPLICATION, (
        "how do i apply", "i want to buy", "want to buy", "apply", "sign up",
        "enrol", "enroll", "register", "documents do i need", "documents i need",
        "proceed with", "ready to get", "take up the plan", "buy the plan",
        "purchase the plan", "how can i pay", "when can the policy start",
        "how to pay", "policy start",
    )),
    (Intent.CORPORATE_NEED, (
        "employee", "employees", "company", "companies", "sme", "business",
        "corporate", "staff", "workforce", "employer", "group insurance",
    )),
    (Intent.FAMILY_NEED, (
        "spouse", "wife", "husband", "child", "children", "daughter", "son",
        "family", "add my", "dependant", "dependent",
    )),
    (Intent.COMPARISON, (
        "cheaper", "another insurer", "other insurer", "competitor",
        "compare", "versus", " vs ", "difference between", "different from",
        "better than", "how are you different",
    )),
    (Intent.CLAIMS, (
        "claim", "claims", "reimburse", "reimbursement", "payout", "submit a claim",
    )),
    (Intent.WAITING_PERIOD, (
        "waiting period", "how soon can i", "when can i claim", "effective immediately",
    )),
    (Intent.ELIGIBILITY, (
        "eligible", "eligibility", "qualify", "age limit", "citizen",
        "foreigner", "can i buy if",
    )),
    (Intent.PAYMENT, (
        "medisave", "pay by", "payment method", "monthly", "instalment",
        "how to pay", "cash",
    )),
    (Intent.PRICE, (
        "price", "cost", "how much", "premium", "rate", "rates", "expensive",
        "cheap", "cheapest", "quote", "quotation", "s$", "dollar",
    )),
    (Intent.COVERAGE, (
        "cover", "coverage", "hospital", "benefit", "benefits", "limit",
        "private", "outpatient", "inpatient", "specialist", "emergency",
        "protection", "insurance", "health insurance", "learn about",
        "what is", "tell me about", "more about",
        "introduce", "what plans", "what products", "what options",
        "basic info", "basic information",
        # Direct plan interest ("I want Plus", "I'm interested in Plus").
        # These express product interest (advance Cold Lead -> Potential
        # Interest) but must NOT be Application/Purchase, so they never jump
        # straight to High Intent.
        "want plus", "want essential", "want the plus", "want the essential",
        "want the family plan", "want a plan", "interested in plus",
        "interested in essential", "interested in the plan",
        "interested in a plan", "like plus", "like the plus",
        "looking for a plan",
    )),
]

# Short affirmative / follow-up phrases that need conversation context to resolve
_AFFIRMATIVE = frozenset((
    "yes", "yeah", "yep", "ok", "okay", "sure", "right", "correct",
    "that's right", "sounds good", "i agree", "please", "go ahead",
))

# Mapping from recent agent-message keywords to the intent a "yes" answer implies
_AGENT_TOPIC_TO_INTENT = {
    "premium": Intent.PRICE,
    "price": Intent.PRICE,
    "cost": Intent.PRICE,
    "apply": Intent.APPLICATION,
    "documents": Intent.APPLICATION,
    "coverage": Intent.COVERAGE,
    "eligible": Intent.ELIGIBILITY,
    "claim": Intent.CLAIMS,
    "family": Intent.FAMILY_NEED,
    "employee": Intent.CORPORATE_NEED,
}


class IntentClassifier:
    def detect(
        self,
        text: str,
        context: list[Message] | None = None,
    ) -> Intent:
        """Classify the customer's intent.

        If the current message matches a keyword, use that directly.
        Otherwise, if it is a short affirmative (e.g. "yes"), look at the
        conversation history to infer what the customer is confirming.
        """
        normalized = f" {text.lower().strip()} "
        for intent, phrases in _INTENT_PHRASES:
            if any(phrase in normalized for phrase in phrases):
                return intent

        # Ambiguous short message — use conversation context
        if context and len(text.split()) <= 4:
            return self._infer_from_context(text.lower().strip(), context)

        return Intent.GENERIC

    @staticmethod
    def _infer_from_context(text: str, context: list[Message]) -> Intent:
        """Infer intent from recent conversation when the message is ambiguous."""
        # Find the most recent agent message
        agent_msg = None
        for msg in reversed(context):
            if msg.role == "agent":
                agent_msg = msg
                break
        if agent_msg is None:
            return Intent.GENERIC

        agent_text = agent_msg.text.lower()
        if text in _AFFIRMATIVE:
            for keyword, intent in _AGENT_TOPIC_TO_INTENT.items():
                if keyword in agent_text:
                    return intent

        # "how much" / "price" after discussing a product → PRICE
        if any(w in text for w in ("how much", "price", "cost")):
            return Intent.PRICE

        return Intent.GENERIC
