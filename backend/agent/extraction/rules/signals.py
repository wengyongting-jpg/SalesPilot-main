# -*- coding: utf-8 -*-
"""Signal detection by phrase matching.

Signal is the third of three separate questions, and keeping them apart is why there
are three modules here:

    Intent  what the customer is asking
    State   where they are in the buying journey   (kernel, not here)
    Signal  observable evidence in what they wrote

Match order is priority order. Withdrawal is checked first and then subtracts, which
is the point of `P0-2`: "I won't buy anymore" contains the word *buy*, so a naive
scan finds purchase intent in a refusal.

The distinction that `P0-4` turned on is between two phrase sets below. A price
*concern* — "that seems expensive" — is Hesitation. Only an explicit discount or
price-match request is Negotiation. They escalate differently, and a representative
briefed for a medical question who arrives at a haggle is worse off than one briefed
for nothing.
"""
from __future__ import annotations

import re

from ....domain.enums import Intent, Product, Signal

_PHRASES: list[tuple[Signal, tuple[str, ...]]] = [
    (Signal.WITHDRAWAL, (
        "won't buy", "wont buy", "don't want", "do not want", "not interested",
        "no longer interested", "decided not to", "not buying",
        "cancel my application", "forget it", "never mind", "changed my mind",
        "call it off", "back out", "not going to buy", "drop it", "pass on this",
        "no longer want", "don't want the plan", "do not want the plan",
        "don't want it anymore", "decided not to purchase", "decided not to buy",
        "won't purchase", "wont purchase",
    )),
    (Signal.CONVERSION, (
        "completed the payment", "made the payment", "signed up", "i bought",
        "already purchased", "done the application", "policy issued",
        "completed my application", "completed the application",
        "completed my payment", "bought the plan", "purchased the plan",
        "i've bought", "ive bought", "have bought", "have purchased",
        "finished the application", "finished my application",
        "submitted my application and paid", "i have paid", "i've paid",
    )),
    (Signal.HUMAN_REQUEST, (
        "speak to someone", "speak to a person", "talk to a human", "human agent",
        "real person", "call me", "sales rep", "sales representative",
        "someone contact me", "speak to a human", "talk to a person",
        "speak to an agent", "talk to an agent", "to a human", "with a human",
        "speak to a real", "speak with someone", "talk to someone", "human being",
    )),
    (Signal.NEGOTIATION, (
        "discount", "negotiate", "negotiation", "negotiable",
        "match their price", "match the price", "match their quote", "price match",
        "beat their price", "better rate", "better price", "better offer",
        "better deal", "lower the premium", "lower the price", "lower price",
        "reduce the price", "reduce the premium", "cheaper for me",
        "give me a deal", "any promotion", "any promo", "special price",
        "waive", "knock off",
    )),
    (Signal.COMPLIANCE_RISK, (
        "pre-existing", "pre existing", "underwrit", "medical history",
        "diagnosed", "my condition", "chronic", "claim dispute",
        "claim was denied", "claim rejected", "custom quote",
        "personalised quote", "personalized quote",
    )),
    (Signal.PURCHASE, (
        "how do i apply", "apply", "sign up", "enrol", "enroll", "register",
        "documents do i need", "documents i need", "buy", "purchase",
        "proceed with", "ready to get", "take up", "how can i pay",
        "when can the policy start", "how to pay", "want to start this week",
    )),
    (Signal.PURCHASE_PREPARATION, (
        "what documents", "documents do i need", "documents i need",
        "how long does the application", "medical check", "medical exam",
        "start date", "when does cover start", "when can the policy start",
        "application steps", "steps to apply", "what do you need from me to apply",
    )),
    (Signal.HESITATION, (
        "expensive", "too pricey", "pricey", "too much", "cheaper",
        "think about", "let me think", "not sure", "maybe later", "hold off",
        "hesitate", "put it off", "some time to decide", "discuss with",
        "discuss it with", "need to discuss",
    )),
    (Signal.COMPETITIVE, (
        "cheaper", "another insurer", "other insurer", "competitor", "compare",
        "versus", " vs ", "different from", "better deal",
        "how are you different",
    )),
    (Signal.EXPANSION_FAMILY, (
        "add my child", "add my spouse", "add my wife", "add my husband",
        "add my daughter", "add my son", "include my child", "cover my family",
        "my child", "my spouse", "my wife", "my husband", "my kids",
        "can i add", "wife join", "child join", "have a child", "have a kid",
        "have a daughter", "have a son", "a child", "i have children",
        "have kids", "with a kid", "newborn", "expecting", "new baby",
    )),
    (Signal.EXPANSION_CORPORATE, (
        "my employees", "our employees", "our staff", "my staff", "my company",
        "our company", "the team", "employee coverage", "what about employee",
    )),
]

POSTPONE_PHRASES = (
    "later", "think about", "some time", "hold off", "put it off", "not now",
)

CANCEL_PHRASES = (
    "cancel my policy", "want to cancel", "terminate", "stop my policy",
)

# Deterministic markers that the sender is selling to us rather than asking about
# cover. This is the corroboration the qualification gate pairs with the model's
# semantic judgement, and it has to work with no model configured at all.
SOLICITATION_PHRASES = (
    "we sell", "we offer", "we provide", "our database", "our list",
    "buy our", "our product", "our service", "our platform", "partner with us",
    "partnership opportunity", "click here", "visit our", "promo code",
    "limited offer", "limited time offer", "best price guaranteed",
    "insurance leads", "generate leads", "seo", "marketing services",
    "bulk discount for you", "wholesale",
)

_URL = re.compile(r"(https?://|www\.|\b[a-z0-9-]+\.(?:com|net|org|io|shop|xyz)\b)")

# Words that indicate a genuine interest in being insured, used only to avoid
# mislabelling a real customer who happens to mention a website.
_INSURANCE_INTEREST = (
    "cover", "coverage", "insure", "insurance", "premium", "policy", "plan",
    "claim", "hospital", "medical", "health", "deductible", "eligib",
)

_AFFIRMATIVE_HINTS = ("yes", "ok", "okay", "sure", "please", "go ahead", "right")


def detect(
    text: str,
    intent: Intent,
    product: Product,
    context: list | None = None,
) -> tuple[list[Signal], list[str]]:
    """Return the signals present and the concerns they imply."""
    normalised = f" {text.lower().strip()} "
    signals: list[Signal] = []

    for signal, phrases in _PHRASES:
        if any(phrase in normalised for phrase in phrases):
            signals.append(signal)

    # P0-2: an explicit withdrawal outranks the purchase wording inside it.
    if Signal.WITHDRAWAL in signals:
        signals = [
            signal for signal in signals
            if signal not in (Signal.PURCHASE, Signal.PURCHASE_PREPARATION)
        ]

    concerns: list[str] = []
    if Signal.HESITATION in signals:
        concerns.append("Price")
    if Signal.COMPETITIVE in signals:
        concerns.append("Competitor")
    if Signal.NEGOTIATION in signals:
        concerns.append("Negotiation")

    # Asking about family while looking at the family plan is an expansion signal
    # even without the explicit "add my" phrasing.
    if (
        product is Product.FAMILY
        and intent in (Intent.FAMILY_NEED, Intent.APPLICATION)
        and Signal.EXPANSION_FAMILY not in signals
    ):
        signals.append(Signal.EXPANSION_FAMILY)

    # A bare "yes" carries purchase intent only if the assistant had just been
    # talking about applying. Without the context it means nothing.
    if (
        context
        and Signal.PURCHASE not in signals
        and Signal.WITHDRAWAL not in signals
        and text.lower().strip() in _AFFIRMATIVE_HINTS
        and _was_about_applying(context)
    ):
        signals.append(Signal.PURCHASE)

    return signals, concerns


def explicit_application_preparation(text: str) -> bool:
    """High-precision steps/materials wording that should not depend on the model.

    Do not infer preparation from a bare wish to buy or apply. A withdrawal in the
    same message wins, just as it does in the offline signal detector.
    """
    normalised = f" {text.lower().strip()} "
    withdrawal_phrases = next(
        phrases for signal, phrases in _PHRASES if signal is Signal.WITHDRAWAL
    )
    if any(phrase in normalised for phrase in withdrawal_phrases):
        return False
    return any(phrase in normalised for phrase in (
        "application steps", "steps to apply", "documents do i need",
        "documents i need", "what documents", "what do you need from me to apply",
    ))


def is_postponement(text: str) -> bool:
    return any(phrase in text.lower() for phrase in POSTPONE_PHRASES)


def is_cancellation(text: str) -> bool:
    return any(phrase in text.lower() for phrase in CANCEL_PHRASES)


def is_solicitation(text: str) -> bool:
    """Whether the sender appears to be promoting rather than enquiring.

    A URL alone is not enough: a real customer may well paste a comparison site. It
    counts only when the message shows no interest in being insured, which keeps the
    marker specific enough to be worth pairing with a model judgement.
    """
    lowered = text.lower()
    if any(phrase in lowered for phrase in SOLICITATION_PHRASES):
        return True
    if _URL.search(lowered) and not any(
        word in lowered for word in _INSURANCE_INTEREST
    ):
        return True
    return False


def _was_about_applying(context: list) -> bool:
    for message in reversed(context):
        if getattr(message, "role", None) is not None and not message.is_from_customer:
            lowered = message.text.lower()
            return any(
                word in lowered
                for word in ("apply", "proceed", "sign up", "purchase")
            )
    return False
