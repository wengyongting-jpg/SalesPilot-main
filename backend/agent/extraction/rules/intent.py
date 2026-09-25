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

import re

from ....domain.enums import Intent

_PAYMENT_METHOD_QUESTION = re.compile(
    r"\b(?:how\s+(?:can|do)\s+i\s+pay|how\s+to\s+pay|"
    r"can\s+i\s+pay\s+(?:by|with|monthly|annually)|"
    r"what\s+(?:are\s+the\s+)?payment\s+methods?)\b",
    re.IGNORECASE,
)
_EXPLICIT_PURCHASE_COMMITMENT = re.compile(
    r"\b(?:(?:i|we)\s+(?:want|plan|intend|will)\s+to\s+"
    r"(?:buy|purchase|apply|proceed)|"
    r"(?:i'm|i am|we're|we are)\s+ready\s+to\s+"
    r"(?:buy|purchase|apply|proceed|pay)|"
    r"please\s+(?:proceed|sign\s+me\s+up)|let's\s+proceed)\b",
    re.IGNORECASE,
)


def is_payment_method_question(text: str) -> bool:
    """A factual payment enquiry, not a commitment to start a transaction."""
    return bool(_PAYMENT_METHOD_QUESTION.search(text)) and not bool(
        _EXPLICIT_PURCHASE_COMMITMENT.search(text)
    )

_PHRASES: list[tuple[Intent, tuple[str, ...]]] = [
    (Intent.HUMAN_REQUEST, (
        "speak to someone", "speak to a person", "talk to a human", "human agent",
        "real person", "call me", "sales rep", "sales representative",
        "someone contact me", "consultant to contact", "speak to an agent",
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
        "buy the plan", "purchase the plan",
        "when can the policy start", "policy start",
        "submit my application", "where do i submit", "what are the steps",
    )),
    (Intent.COMPARISON, (
        "cheaper", "another insurer", "other insurer", "competitor", "compare",
        "comparing", "versus", " vs ", "difference between", "different from",
        "better than", "how are you different", "which plan",
        # "Which is better, Plus or Essential?" names two products directly
        # rather than using "compare"/"versus" wording, but is exactly as much
        # a comparison request.
        "which is better", "which one is better", "which is best",
        "which one is best", "which should i choose", "which one should i choose",
    )),
    # Specific factual questions (claims, waiting period, eligibility, payment,
    # price) are checked before the family/corporate "orientation" intents
    # below them: a question naming a plan by its product name ("what does the
    # Family plan cover?", "is there a waiting period for Family cover?") is
    # about that specific thing, not a fresh statement of family/corporate
    # need, even though it mentions "family"/"corporate".
    (Intent.CLAIMS, (
        "claim", "claims", "reimburse", "reimbursement", "payout",
        "submit a claim",
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
        "how can i pay", "how do i pay", "how to pay", "cash",
        "paid successfully", "submitted and paid",
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
        "what is", "tell me about", "more about", "introduce", "what plans",
        "what products", "what options", "basic info", "basic information",
        "exclusion", "exclusions",
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

# "Apply" is the one APPLICATION trigger word that also appears in ordinary
# clauses about a plan's terms — "these exclusions apply to..." is a coverage
# question, not a request to submit an application. Narrow to that one
# collision rather than dropping bare "apply", which real application
# phrasing ("...and apply before the school holidays") still needs.
_APPLICATION_FALSE_POSITIVES = (
    "exclusions apply", "exclusion applies", "terms apply", "conditions apply",
)


def detect(text: str, context: list | None = None) -> Intent:
    normalised = f" {text.lower().strip()} "
    for intent, phrases in _PHRASES:
        # Keep the higher-priority human/complaint/underwriting boundaries,
        # then distinguish a factual payment question from an application.
        if intent is Intent.APPLICATION and is_payment_method_question(text):
            return Intent.PAYMENT
        if intent is Intent.APPLICATION and any(
            fp in normalised for fp in _APPLICATION_FALSE_POSITIVES
        ):
            continue
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
