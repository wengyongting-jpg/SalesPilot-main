# -*- coding: utf-8 -*-
"""Intent classification by phrase matching, with context for short messages.

Match order is priority order: the riskiest and most specific intents are checked
first, so "I want to cancel my policy" is a complaint rather than a coverage question.

The `underwriting` intent is named for the business process it triggers, not for its
surface wording. The frozen build's prompt called the same thing `medical_question`,
which the domain then rejected — the drift that made this intent unreachable whenever
a model was configured.
"""
from __future__ import annotations

from ....domain.enums import Intent

_PHRASES: list[tuple[Intent, tuple[str, ...]]] = [
    (Intent.HUMAN_REQUEST, (
        "speak to someone", "speak to a person", "talk to a human", "human agent",
        "real person", "call me", "sales rep", "sales representative",
        "someone contact me", "consultant to contact", "speak to an agent",
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
        "cheaper", "another insurer", "other insurer", "competitor", "compare",
        "versus", " vs ", "difference between", "different from", "better than",
        "how are you different",
    )),
    (Intent.CLAIMS, (
        "claim", "claims", "reimburse", "reimbursement", "payout",
        "submit a claim",
    )),
    (Intent.WAITING_PERIOD, (
        "waiting period", "how soon can i", "when can i claim",
        "effective immediately",
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
        "what is", "tell me about", "more about", "introduce", "what plans",
        "what products", "what options", "basic info", "basic information",
        # Direct plan interest. These advance a cold lead, but they are interest
        # rather than preparation, so they must not be read as an application —
        # otherwise "I want Plus" jumps straight to High Intent.
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

# What a bare "yes" means depends on what was just asked.
_TOPIC_TO_INTENT = {
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

_SHORT_MESSAGE_WORDS = 4


def detect(text: str, context: list | None = None) -> Intent:
    normalised = f" {text.lower().strip()} "
    for intent, phrases in _PHRASES:
        if any(phrase in normalised for phrase in phrases):
            return intent

    if context and len(text.split()) <= _SHORT_MESSAGE_WORDS:
        return _from_context(text.lower().strip(), context)

    return Intent.GENERIC


def _from_context(text: str, context: list) -> Intent:
    """Resolve an ambiguous short message against what was last discussed."""
    last_business = None
    for message in reversed(context):
        if getattr(message, "role", None) is not None and not message.is_from_customer:
            last_business = message
            break
    if last_business is None:
        return Intent.GENERIC

    lowered = last_business.text.lower()
    if text in _AFFIRMATIVE:
        for keyword, intent in _TOPIC_TO_INTENT.items():
            if keyword in lowered:
                return intent

    if any(word in text for word in ("how much", "price", "cost")):
        return Intent.PRICE

    return Intent.GENERIC
