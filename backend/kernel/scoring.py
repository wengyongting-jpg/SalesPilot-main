# -*- coding: utf-8 -*-
"""The opportunity value score: two axes, scored separately.

Specification: `docs/backend-contract.md` gap register item 13.

    Fit (0-100)        how appropriate and how valuable this opportunity is
        need_identified      40
        product_potential    40
        expansion            20

    Behaviour (0-100)  how actively they are buying right now
        purchase_intent      40
        purchase_readiness   30
        engagement           30  =  depth 24 + urgency 6
        then the whole axis is multiplied by a recency factor

Three properties the previous single-axis model lacked, each named by the industry
convention as a failure mode when absent:

1. **Fit is separate from behaviour.** Deal size and expansion breadth describe what
   the opportunity is worth, not how warm it is. Leaving them in the behavioural
   total is what let a noisy conversation about an expensive plan look like an active
   buyer.
2. **Genuineness is a fit question.** A conversation that is not a sales enquiry has
   a fit of zero, whatever it does. That single rule is what stops advertising
   traffic from ranking: on the frozen build it reached 96 points against a genuine
   customer's 82.
3. **Behavioural evidence decays, multiplicatively.** The dimension is named
   "Engagement & Urgency" and the previous implementation was
   `min(12, 3 + 2 * message_count)` — a pure counter with no notion of time, so a
   conversation abandoned a month ago kept full marks.

   Decay multiplies the whole behaviour axis rather than contributing a term to it.
   That was a correction made during implementation: as an additive dimension worth
   ten of a hundred points, recency could not move a band, so a high-fit
   conversation with forty days of silence still came out HIGH. Decay means stale
   evidence *counts for less*, which is a scaling, not a subtraction. Fit is not
   decayed — how valuable an opportunity would be does not change because nobody has
   spoken lately; only the strength of the evidence that they are buying does.

Risk flags — competitive, compliance, human request — add no points on either axis.
They drive next best action and escalation instead, so a risky opportunity is
surfaced by the recommended action rather than by an inflated number.

The score is for sales prioritisation only. It is never an input to eligibility,
pricing, underwriting, claims or any medical decision.

`now` is injected rather than read from the clock, so a score is reproducible from
stored data and recency behaviour is testable.
"""
from __future__ import annotations

from datetime import datetime

from ..domain.detection import Detection
from ..domain.enums import Intent, Priority, Product, Qualification, Signal
from ..domain.opportunity import Opportunity, ScoreCard
from . import priority as priority_rules

# ---- Fit ------------------------------------------------------------------

_PRODUCT_POTENTIAL = {
    Product.ESSENTIAL: 10,
    Product.FAMILY: 20,
    Product.PLUS: 30,
    Product.CORPORATE: 40,
    Product.UNKNOWN: 0,
}

# ---- Behaviour ------------------------------------------------------------

_URGENCY_PHRASES = (
    "urgent", "urgently", "asap", "as soon as possible", "right away",
    "by tomorrow", "this week", "next week", "soon",
)

# How much buying signal each intent carries. Used as a high-water mark so a later
# vague message cannot erase intent the conversation already established.
_INTENT_STRENGTH = {
    Intent.GENERIC: 0,
    Intent.HUMAN_REQUEST: 1,
    Intent.COMPLAINT: 1,
    Intent.CLAIMS: 2,
    Intent.WAITING_PERIOD: 2,
    Intent.PAYMENT: 3,
    Intent.ELIGIBILITY: 3,
    Intent.UNDERWRITING: 3,
    Intent.FAMILY_NEED: 4,
    Intent.CORPORATE_NEED: 4,
    Intent.COVERAGE: 5,
    Intent.PRICE: 5,
    Intent.COMPARISON: 5,
    Intent.APPLICATION: 6,
}

_FACTUAL_INTENTS = {
    Intent.PRICE, Intent.COVERAGE, Intent.CLAIMS,
    Intent.PAYMENT, Intent.ELIGIBILITY, Intent.WAITING_PERIOD,
}

# Diminishing returns, with a ceiling. The old formula rewarded volume linearly
# until it clipped, which meant a repetitive sender out-scored a concise one.
_DEPTH_BY_MESSAGES = {0: 0, 1: 7, 2: 12, 3: 16, 4: 18, 5: 19, 6: 21, 7: 22}
_DEPTH_MAX = 24
_URGENCY_POINTS = 6

# Recency as a percentage multiplier on the behaviour axis, by hours since the
# customer last said anything. The floor is not zero: a long-silent conversation is
# weak evidence, not an absence of evidence, and zeroing it would erase the history
# a representative needs when re-engaging.
_RECENCY_FACTOR_BANDS = (
    (6, 100),
    (24, 95),
    (72, 85),
    (24 * 7, 70),
    (24 * 30, 50),
)
_RECENCY_FLOOR = 35


def intent_strength(intent: Intent) -> int:
    return _INTENT_STRENGTH.get(intent, 2)


def effective_intent(current: Intent, best_so_far: Intent) -> Intent:
    """Whichever of this turn's intent and the conversation's best is stronger."""
    if intent_strength(current) >= intent_strength(best_so_far):
        return current
    return best_so_far


def score(
    opp: Opportunity,
    det: Detection,
    latest_text: str,
    *,
    now: datetime,
) -> ScoreCard:
    signals = set(opp.signals) | set(det.signals)
    text = latest_text.lower()
    withdrawn = Signal.WITHDRAWAL in signals
    intent = effective_intent(det.intent, opp.best_intent)

    # Genuineness is a fit question, so it zeroes the fit axis rather than being
    # subtracted from a total. A conversation that is not an enquiry is not a
    # valuable opportunity at any deal size.
    sellable = det.genuine_enquiry and opp.qualification is Qualification.QUALIFIED

    need_identified = _need_identified(intent, opp.product) if sellable else 0
    product_potential = _PRODUCT_POTENTIAL.get(opp.product, 0) if sellable else 0
    expansion = _expansion(det, signals) if sellable else 0
    fit_total = need_identified + product_potential + expansion

    purchase_intent = _purchase_intent(intent, signals, withdrawn)
    readiness = _readiness(intent, signals, text, withdrawn)
    depth, urgency = _engagement_parts(opp, text, withdrawn=withdrawn)
    engagement = depth + urgency
    recency_factor = _recency_factor(opp, now=now)

    behaviour_raw = min(100, purchase_intent + readiness + engagement)
    behaviour_total = round(behaviour_raw * recency_factor / 100)
    fit_total = min(100, fit_total)

    return ScoreCard(
        need_identified=need_identified,
        product_potential=product_potential,
        expansion=expansion,
        fit_total=fit_total,
        purchase_intent=purchase_intent,
        purchase_readiness=readiness,
        engagement=engagement,
        engagement_depth=depth,
        engagement_urgency=urgency,
        engagement_recency=recency_factor,
        behaviour_raw=behaviour_raw,
        behaviour_total=behaviour_total,
        total=round((fit_total + behaviour_total) / 2),
        priority=priority_rules.derive(
            fit_total, behaviour_total, opp.qualification, withdrawn=withdrawn
        ),
    )


# ---- Fit dimensions -------------------------------------------------------


def _need_identified(intent: Intent, product: Product) -> int:
    """Is there a real insurance need, and is it one CareSure sells?"""
    if intent is Intent.GENERIC:
        return 0
    if product is Product.UNKNOWN:
        # A need is evident but not yet attached to a plan.
        return 20
    return 40


def _expansion(det: Detection, signals: set[Signal]) -> int:
    if Signal.EXPANSION_CORPORATE in signals:
        return 20
    if Signal.EXPANSION_FAMILY in signals:
        return 13
    if det.intent is Intent.FAMILY_NEED:
        return 7
    return 0


# ---- Behaviour dimensions -------------------------------------------------


def _purchase_intent(intent: Intent, signals: set[Signal], withdrawn: bool) -> int:
    if withdrawn:
        return 3
    if Signal.CONVERSION in signals:
        return 40
    if Signal.PURCHASE in signals and intent is Intent.APPLICATION:
        return 37
    if Signal.PURCHASE in signals:
        return 33
    if intent in (Intent.PRICE, Intent.COVERAGE, Intent.COMPARISON):
        return 24
    if intent in (Intent.FAMILY_NEED, Intent.CORPORATE_NEED):
        return 20
    if intent is Intent.GENERIC:
        return 6
    return 13


def _readiness(intent: Intent, signals: set[Signal], text: str, withdrawn: bool) -> int:
    if withdrawn:
        return 3
    if Signal.CONVERSION in signals:
        return 30
    documents = any(word in text for word in ("document", "apply", "sign up", "proceed"))
    payment = any(word in text for word in ("pay", "payment"))
    if Signal.PURCHASE in signals:
        return 27 if (documents or payment) else 21
    if intent is Intent.COMPARISON or Signal.COMPETITIVE in signals:
        return 13
    if intent in _FACTUAL_INTENTS:
        return 10
    if intent in (Intent.FAMILY_NEED, Intent.CORPORATE_NEED):
        return 9
    return 4


def _engagement_parts(
    opp: Opportunity, text: str, *, withdrawn: bool
) -> tuple[int, int]:
    """Depth and urgency, as two separate readings.

    Reported separately rather than summed silently, so the admin surface can show
    *why* engagement is what it is. "Engagement 24" is not reviewable; "depth 18,
    urgency 6" is.
    """
    depth = _DEPTH_BY_MESSAGES.get(opp.customer_message_count, _DEPTH_MAX)

    if withdrawn:
        return depth, 0

    observed_now = any(phrase in text for phrase in _URGENCY_PHRASES)
    urgency = _URGENCY_POINTS if (opp.urgency_observed or observed_now) else 0
    return depth, urgency


def _recency_factor(opp: Opportunity, *, now: datetime) -> int:
    """How much the behavioural evidence still counts, as a percentage.

    A multiplier rather than a dimension: see the module docstring. Fit is not
    multiplied — silence does not make a corporate account worth less, it makes the
    evidence that they are buying weaker.
    """
    last_seen = opp.last_customer_message_at
    if last_seen is None:
        return _RECENCY_FLOOR
    hours = max(0.0, (now - last_seen).total_seconds() / 3600.0)
    for limit, factor in _RECENCY_FACTOR_BANDS:
        if hours < limit:
            return factor
    return _RECENCY_FLOOR


def urgency_in(text: str) -> bool:
    """Whether a message expresses urgency.

    Exposed so the profile update step can raise the `urgency_observed` high-water
    mark. Scoring itself stays pure and mutates nothing.
    """
    lowered = text.lower()
    return any(phrase in lowered for phrase in _URGENCY_PHRASES)
