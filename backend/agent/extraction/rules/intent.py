# -*- coding: utf-8 -*-
"""Intent classifier — what the customer is asking about.

Keyword matching with conversation-history context resolution: an ambiguous
short message (e.g. "yes", "how much") is resolved against the most recent
business message. Ported from `salespilot/detection/intent.py`, retargeted to
`backend.domain.enums.Intent` (12 members, including `UNDERWRITING` — the
frozen build's prompt never offered this value to the model, which is part of
the drift `backend/README.md` describes; the rule-based peer always had it).

Match order is priority: high-risk / strong intents come first.
"""
from __future__ import annotations

from typing import Optional

from ....domain.enums import Intent
from ....domain.message import Message

_INTENT_PHRASES: list[tuple[Intent, tuple[str, ...]]] = [
    (Intent.HUMAN_REQUEST, (
        "speak to someone", "speak to a person", "talk to a human", "human agent",
        "real person", "call me", "sales rep", "sales representative",
        "someone contact me", "consultant to contact",
        "speak to a human", "talk to a person", "speak to an agent",
        "talk to an agent", "to a human", "with a human", "speak to a real",
        "speak with someone", "talk to someone", "human being",
        "manager to resolve", "speak to a manager", "want a manager",
        "someone to confirm",
    )),
    (Intent.COMPLAINT, (
        "complaint", "complain", "not happy", "unhappy", "frustrated",
        "want to cancel", "cancel my policy", "dispute", "denied claim",
        "claim was rejected", "unacceptable", "nobody replies", "no response",
    )),
    (Intent.UNDERWRITING, (
        "pre-existing", "pre existing", "underwrit", "medical history",
        "diagnosed", "my condition", "chronic", "asthma", "diabetes",
        "existing condition",
    )),
    (Intent.APPLICATION, (
        "how do i apply", "i want to buy", "want to buy", "apply", "sign up",
        "enrol", "enroll", "register", "documents do i need", "documents i need",
        "proceed with", "want to proceed", "ready to get", "take up the plan",
        "buy the plan", "purchase the plan", "how can i pay",
        "when can the policy start", "how to pay", "policy start",
        "submit my application", "where do i submit", "what are the steps",
    )),
    (Intent.COMPARISON, (
        "cheaper", "another insurer", "other insurer", "competitor",
        "compare", "comparing", "versus", " vs ", "difference between",
        "different from", "better than", "how are you different",
    )),
    # Specific factual questions (claims, waiting period, eligibility, payment,
    # price) are checked before the family/corporate "orientation" intents
    # below them: a question naming a plan by its product name ("what does the
    # Family plan cover?", "is there a waiting period for Family cover?") is
    # about that specific thing, not a fresh statement of family/corporate
    # need, even though it mentions "family"/"corporate".
    (Intent.CLAIMS, (
        "claim", "claims", "reimburse", "reimbursement", "payout", "submit a claim",
    )),
    (Intent.WAITING_PERIOD, (
        "waiting period", "how soon can i", "when can i claim",
        "effective immediately", "start using", "when can i use",
        "when does cover start", "when will i be covered",
    )),
    (Intent.ELIGIBILITY, (
        "eligible", "eligibility", "qualify", "age limit", "citizen",
        "foreigner", "can i buy if",
    )),
    (Intent.PAYMENT, (
        "medisave", "pay by", "payment method", "monthly", "instalment",
        "how to pay", "cash", "paid successfully", "submitted and paid",
        "completed payment", "completed the payment",
    )),
    (Intent.PRICE, (
        "price", "cost", "how much", "premium", "the rate", "your rate",
        "insurance rate", "rates for", "expensive", "cheap", "cheapest",
        "quote", "quotation", "s$", "dollar",
    )),
    (Intent.CORPORATE_NEED, (
        # Deliberately no bare "corporate": "the corporate plan" names a
        # product, it is not by itself a statement of corporate need, and a
        # bare match here was intercepting factual questions about a named
        # corporate plan before they ever reached coverage/price above.
        "employee", "employees", "company", "companies", "sme", "business",
        "staff", "workforce", "employer", "group insurance",
    )),
    (Intent.FAMILY_NEED, (
        # Deliberately no bare "family", for the same reason: "the Family
        # plan"/"Family cover" names a product.
        "spouse", "wife", "husband", "child", "children", "daughter", "son",
        "add my", "dependant", "dependent",
    )),
    (Intent.COVERAGE, (
        "cover", "coverage", "hospital", "benefit", "benefits", "limit",
        "private", "outpatient", "inpatient", "specialist", "emergency",
        "protection", "insurance", "health insurance", "learn about",
        "what is", "tell me about", "more about",
        "introduce", "what plans", "what products", "what options",
        "basic info", "basic information", "exclusion", "exclusions",
        "want plus", "want essential", "want the plus", "want the essential",
        "want the family plan", "want a plan", "interested in plus",
        "interested in essential", "interested in the plan",
        "interested in a plan", "like plus", "like the plus",
        "looking for a plan",
    )),
]

_AFFIRMATIVE = frozenset((
    "yes", "yeah", "yep", "ok", "okay", "sure", "right", "correct",
    "that's right", "sounds good", "i agree", "please", "go ahead",
))

_BUSINESS_TOPIC_TO_INTENT = {
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


# "Apply" is the one APPLICATION trigger word that also appears in ordinary
# clauses about a plan's terms — "these exclusions apply to..." is a coverage
# question, not a request to submit an application. Narrow to that one
# collision rather than dropping bare "apply", which real application
# phrasing ("...and apply before the school holidays") still needs.
_APPLICATION_FALSE_POSITIVES = (
    "exclusions apply", "exclusion applies", "terms apply", "conditions apply",
)


def detect(text: str, context: Optional[list[Message]] = None) -> Intent:
    """Classify the customer's intent from keywords, or from context when ambiguous."""
    normalized = f" {text.lower().strip()} "
    for intent, phrases in _INTENT_PHRASES:
        if intent is Intent.APPLICATION and any(
            fp in normalized for fp in _APPLICATION_FALSE_POSITIVES
        ):
            continue
        if any(phrase in normalized for phrase in phrases):
            return intent

    if context and len(text.split()) <= 4:
        return _infer_from_context(text.lower().strip(), context)

    return Intent.GENERIC


def _infer_from_context(text: str, context: list[Message]) -> Intent:
    business_msg = None
    for msg in reversed(context):
        if not msg.is_from_customer:
            business_msg = msg
            break
    if business_msg is None:
        return Intent.GENERIC

    business_text = business_msg.text.lower()
    if text in _AFFIRMATIVE:
        for keyword, intent in _BUSINESS_TOPIC_TO_INTENT.items():
            if keyword in business_text:
                return intent

    if any(w in text for w in ("how much", "price", "cost")):
        return Intent.PRICE

    return Intent.GENERIC
