# -*- coding: utf-8 -*-
"""Sales signal, lifecycle and qualification observation detector.

Signal, cancellation/postponement and solicitation detection are kept
together because they all read the same normalized text once. Ported from
`salespilot/detection/signals.py`, retargeted to the full 11-member
`backend.domain.enums.Signal` (the frozen build's model-facing prompt only
offered 7 of these — see `backend/README.md` — the rule-based peer always had
all 11) and extended with `solicitation` detection, new in the rebuild: the
deterministic corroboration `backend.kernel.qualification` needs alongside
the model's `genuine_enquiry` judgement.
"""
from __future__ import annotations

import re
import unicodedata
from typing import NamedTuple, Optional

from ....domain.enums import Intent, Product, Signal
from ....domain.message import Message

_SIGNAL_PHRASES: list[tuple[Signal, tuple[str, ...]]] = [
    (Signal.WITHDRAWAL, (
        "won't buy", "wont buy", "don't want", "do not want", "not interested",
        "no longer interested", "decided not to", "not buying",
        "cancel my application", "cancel my policy", "forget it", "never mind",
        "changed my mind", "call it off", "back out",
        "i won't buy anymore", "won't buy anymore", "not going to buy",
        "drop it", "scrapped", "pass on this",
        "don't want to buy", "do not want to buy", "won't buy anymore",
        "no longer want", "don't want the plan", "do not want the plan",
        "don't want it anymore", "decided not to purchase", "decided not to buy",
        "not to purchase", "won't purchase", "wont purchase",
        # A specific, multi-month deferral reads differently from a vague
        # "let me think about it": without this, the state machine still
        # (correctly) moves the opportunity to Dormant/Lost via postponement,
        # but with no Withdrawal signal the next-best-action for that state
        # is still nurture-style follow-up, which means pushing a question on
        # someone who just asked for months of space. Withdrawn's guidance
        # ("acknowledge warmly, do not attempt to persuade") fits what they
        # actually asked for.
        "for a few months", "for several months", "for months", "for a year",
    )),
    (Signal.CONVERSION, (
        "completed the payment", "completed payment", "made the payment",
        "paid", "signed up", "i bought", "already purchased",
        "done the application", "policy issued", "completed my application",
        "completed the application", "completed my payment",
        "completed my application and payment", "bought the plan",
        "purchased the plan", "i've bought", "ive bought", "have bought",
        "have purchased", "finished the application", "finished my application",
        "submitted my application and paid",
    )),
    (Signal.HUMAN_REQUEST, (
        "speak to someone", "speak to a person", "talk to a human", "human agent",
        "real person", "call me", "sales rep", "sales representative",
        "someone contact me",
        "speak to a human", "talk to a person", "speak to an agent",
        "talk to an agent", "to a human", "with a human", "speak to a real",
        "speak with someone", "talk to someone", "human being",
        "manager to resolve", "speak to a manager", "want a manager",
        "someone to confirm",
    )),
    (Signal.NEGOTIATION, (
        "discount", "negotiate", "negotiation", "negotiable",
        "match their price", "match the price", "match that price",
        "match your price", "match their quote", "price match",
        "beat their price", "better rate", "better price", "better offer",
        "better deal", "lower the premium", "lower the price", "lower price",
        "reduce the price", "reduce the premium", "cheaper for me",
        "give me a deal", "any promotion", "any promo", "special price",
        "waive", "knock off",
    )),
    (Signal.COMPLIANCE_RISK, (
        "pre-existing", "pre existing", "underwrit", "medical history",
        "diagnosed", "my condition", "existing condition", "chronic",
        "asthma", "diabetes", "had surgery", "claim dispute",
        "claim was denied", "claim rejected",
        "custom quote", "personalised quote", "personalized quote",
    )),
    (Signal.PURCHASE, (
        "how do i apply", "apply", "sign up", "enrol", "enroll", "register",
        "documents do i need", "documents i need", "buy", "purchase",
        "proceed with", "want to proceed", "ready to get", "take up",
        "how can i pay", "when can the policy start", "how to pay",
        "i have chosen", "i've chosen", "chosen the plan", "i will sign",
        "sign today",
    )),
    (Signal.HESITATION, (
        "expensive", "too pricey", "pricey", "too much", "cheaper",
        "think about", "let me think", "not sure", "maybe later",
        "hold off", "hesitate", "put it off", "some time to decide",
        "discuss with", "discuss it with", "need to discuss", "not ready",
        "more than i expected", "than i expected",
        "does not answer my question", "doesn't answer my question",
    )),
    (Signal.COMPETITIVE, (
        "cheaper", "another insurer", "other insurer", "competitor",
        "compare", "comparing", "versus", " vs ", "different from",
        "better deal", "how are you different",
    )),
    (Signal.EXPANSION_FAMILY, (
        "add my child", "add my spouse", "add my wife", "add my husband",
        "add my daughter", "add my son", "include my child", "cover my family",
        "my child", "my children", "my spouse", "my wife", "my husband",
        "my kids", "can i add", "wife join", "child join",
        "have a child", "have a kid", "have a daughter", "have a son",
        "a child", "i have children", "have kids", "with a kid",
        "newborn", "expecting", "new baby",
    )),
    (Signal.EXPANSION_CORPORATE, (
        "my employees", "our employees", "our staff", "my staff",
        "my company", "our company", "120 employees", "the team",
        "employee coverage", "what about employee",
    )),
]

_POSTPONE_PHRASES = (
    "later", "think about", "some time", "hold off", "put it off", "not now",
    "next year", "revisit this", "revisit next",
)

_CANCEL_PHRASES = (
    "cancel my policy", "want to cancel", "terminate", "stop my policy",
)

# Advertising/promotion vocabulary: the deterministic corroboration that a
# message is solicitation rather than a genuine enquiry. Kept narrow and
# specific on purpose — a false positive here would wrongly hold a real lead.
_SOLICITATION_PHRASES = (
    "check out our", "visit our website", "limited time offer",
    "click the link", "click here", "dm us", "whatsapp us at",
    "we offer the best", "best deals on", "grow your business",
    "increase your followers", "buy now and save", "act now",
    "exclusive deal for you", "subscribe to our",
    # A genuine customer asking for a person wants *our* customer-facing team
    # about their own case ("a manager", "someone in charge"). Asking to
    # reach our marketing/sales/procurement contact instead is the B2B-spam
    # pattern of angling for a pitch meeting, not seeking help buying cover.
    "your marketing manager", "your marketing team", "marketing manager call",
    "your procurement", "your purchasing department",
)

# "my two children"/"my three kids": a quantifier between "my" and the family
# word defeats the literal "my child"/"my children" phrases above.
_FAMILY_COUNT = re.compile(r"\bmy\s+\w+\s+(child|children|kids?|daughters?|sons?)\b")

_CONTEXT_PURCHASE_HINTS = ("yes", "ok", "sure", "please", "go ahead", "right")

# Common leetspeak/homoglyph digit-for-letter substitutions. A phrase match is
# tried against both the plain-lowercased text and this de-leeted copy, so a
# restricted-topic phrase like "discount" cannot dodge escalation by being
# spelled "disc0unt" — escalation gates (`kernel.hitl`) must not be this easy
# to route around with trivial obfuscation.
_LEET_MAP = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"})


def _deleet(text: str) -> str:
    return text.translate(_LEET_MAP)


def _strip_invisible(text: str) -> str:
    """Drop Unicode "format" characters (zero-width space/joiner, bidi
    controls, byte-order mark, ...) that render as nothing but still break a
    literal substring match. `"disc​ount"` reads identically to
    "discount" to a person and to any UI, so it must match "discount" here
    too rather than silently slipping past every restricted-topic phrase.
    """
    return "".join(ch for ch in text if unicodedata.category(ch) != "Cf")


class SignalObservations(NamedTuple):
    signals: list[Signal]
    concerns: list[str]
    restricted: bool
    cancellation: bool
    postponement: bool
    solicitation: bool


def detect(
    text: str,
    intent: Intent,
    product: Product,
    context: Optional[list[Message]] = None,
) -> SignalObservations:
    """Detect observable sales signals, lifecycle events, and solicitation."""
    cleaned = _strip_invisible(text)
    normalized = f" {cleaned.lower().strip()} "
    deleeted = f" {_deleet(cleaned.lower().strip())} "
    signals: list[Signal] = []
    concerns: list[str] = []

    for signal, phrases in _SIGNAL_PHRASES:
        if any(phrase in normalized or phrase in deleeted for phrase in phrases):
            signals.append(signal)

    if _FAMILY_COUNT.search(normalized) and Signal.EXPANSION_FAMILY not in signals:
        signals.append(Signal.EXPANSION_FAMILY)

    # Withdrawal is a strong negative signal and overrides a co-occurring
    # purchase keyword match on the same message (e.g. "I won't buy anymore").
    if Signal.WITHDRAWAL in signals:
        signals = [s for s in signals if s != Signal.PURCHASE]

    if Signal.HESITATION in signals:
        concerns.append("Price")
    if Signal.COMPETITIVE in signals:
        concerns.append("Competitor")
    if Signal.NEGOTIATION in signals:
        concerns.append("Negotiation")

    if (
        product is Product.FAMILY
        and intent in (Intent.FAMILY_NEED, Intent.APPLICATION)
        and Signal.EXPANSION_FAMILY not in signals
    ):
        signals.append(Signal.EXPANSION_FAMILY)

    # The corporate mirror of the family fallback above: "cover for 85
    # employees" is a corporate expansion need even though it never says "my
    # employees"/"our staff" — the explicit-phrase list only catches an
    # existing customer adding headcount, not a fresh corporate enquiry.
    if (
        product is Product.CORPORATE
        and intent in (Intent.CORPORATE_NEED, Intent.APPLICATION)
        and Signal.EXPANSION_CORPORATE not in signals
    ):
        signals.append(Signal.EXPANSION_CORPORATE)

    if (
        context
        and Signal.PURCHASE not in signals
        and Signal.WITHDRAWAL not in signals
        and cleaned.lower().strip() in _CONTEXT_PURCHASE_HINTS
        and _was_application_topic(context)
    ):
        signals.append(Signal.PURCHASE)

    restricted = (
        Signal.HUMAN_REQUEST in signals
        or Signal.COMPLIANCE_RISK in signals
        or Signal.NEGOTIATION in signals
    )
    lowered = cleaned.lower()
    return SignalObservations(
        signals=signals,
        concerns=concerns,
        restricted=restricted,
        cancellation=any(p in lowered for p in _CANCEL_PHRASES),
        postponement=any(p in lowered for p in _POSTPONE_PHRASES),
        solicitation=any(p in lowered for p in _SOLICITATION_PHRASES),
    )


def _was_application_topic(context: list[Message]) -> bool:
    for msg in reversed(context):
        if not msg.is_from_customer:
            text = msg.text.lower()
            return any(k in text for k in ("apply", "proceed", "sign up", "purchase"))
    return False
