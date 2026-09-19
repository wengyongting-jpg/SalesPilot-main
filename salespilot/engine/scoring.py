# -*- coding: utf-8 -*-
"""Opportunity Value Score — unified 100-point model.

Dimensions and weights:
  Purchase Intent        30
  Purchase Readiness     20
  Product Potential      20  (Essential 5 / Family 10 / Plus 15 / Corporate 20)
  Expansion Opportunity  15
  Engagement & Urgency   15

Critical: Competitive Risk, Compliance Risk, and Human Request do NOT add
points to the score. They affect Next Best Action / HITL instead.

The score is for sales prioritisation only — never for eligibility, pricing,
underwriting, claims, or medical decisions.
"""
from .. import config
from ..models import (
    Detection,
    Intent,
    Opportunity,
    Priority,
    Product,
    ScoreCard,
    Signal,
)

_PRODUCT_POTENTIAL = {
    Product.ESSENTIAL: 5,
    Product.FAMILY: 10,
    Product.PLUS: 15,
    Product.CORPORATE: 20,
    Product.UNKNOWN: 0,
}

_URGENCY_PHRASES = ("urgent", "asap", "by tomorrow", "next week", "this week", "soon")

# Ranking of intents by how much buying signal they carry. Used so that a
# later, more generic message cannot erase purchase intent that the
# conversation already established (the opportunity profile is persistent
# memory — score is computed from the accumulated history, not one message).
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


class PriorityEngine:
    def score(
        self,
        opp: Opportunity,
        det: Detection,
        latest_text: str,
    ) -> ScoreCard:
        # Use signals accumulated on the opportunity profile (the score
        # evolves with the conversation, not just the current turn).
        signals = set(opp.signals) | set(det.signals)
        text = latest_text.lower()

        # --- Withdrawal overrides all positive signals ---
        if Signal.WITHDRAWAL in det.signals or Signal.WITHDRAWAL in opp.signals:
            return ScoreCard(
                purchase_intent=2,
                purchase_readiness=2,
                product_potential=_PRODUCT_POTENTIAL.get(opp.product, 0),
                expansion=0,
                engagement=2,
                total=min(20, _PRODUCT_POTENTIAL.get(opp.product, 0) + 6),
                priority=Priority.LOW,
            )

        # Effective intent = the strongest intent seen this turn OR previously.
        # best_intent is the persistent high-water mark maintained on the
        # profile, so a later "ok" / "still thinking" generic message does not
        # reset previously established purchase intent to cold-lead.
        effective_intent = self._effective_intent(det.intent, opp.best_intent)
        scoring_det = Detection(
            intent=effective_intent,
            product=det.product,
            signals=det.signals,
            concerns=det.concerns,
            restricted=det.restricted,
        )

        purchase_intent = self._intent_score(scoring_det, signals)
        readiness = self._readiness_score(scoring_det, signals, text)
        product_potential = _PRODUCT_POTENTIAL.get(opp.product, 0)
        # Unknown product: 0-5 based only on observable need
        if opp.product == Product.UNKNOWN and effective_intent != Intent.GENERIC:
            product_potential = 3
        expansion = self._expansion_score(scoring_det, signals)
        engagement = self._engagement_score(opp, text)

        total = min(
            100,
            purchase_intent + readiness + product_potential + expansion + engagement,
        )
        priority = self._band(total)
        return ScoreCard(
            purchase_intent=purchase_intent,
            purchase_readiness=readiness,
            product_potential=product_potential,
            expansion=expansion,
            engagement=engagement,
            total=total,
            priority=priority,
        )

    @staticmethod
    def _band(total: int) -> Priority:
        if total >= config.HIGH_PRIORITY_MIN:
            return Priority.HIGH
        if total >= config.MEDIUM_PRIORITY_MIN:
            return Priority.MEDIUM
        return Priority.LOW

    @staticmethod
    def intent_strength(intent: Intent) -> int:
        """How much buying signal an intent carries (higher = stronger)."""
        return _INTENT_STRENGTH.get(intent, 2)

    @classmethod
    def _effective_intent(cls, current: Intent, best_so_far: Intent) -> Intent:
        """Return whichever of the current / previously-best intent is stronger.

        This makes the score reflect accumulated opportunity history rather
        than only the latest message, so a later generic reply cannot collapse
        an opportunity back to a cold lead.
        """
        if cls.intent_strength(current) >= cls.intent_strength(best_so_far):
            return current
        return best_so_far

    # ---- Dimension rules ------------------------------------------------

    @staticmethod
    def _intent_score(det: Detection, signals: set[Signal]) -> int:
        """0-5 generic, 6-15 shows interest, 16-24 evaluates, 25-30 explicit."""
        if Signal.CONVERSION in signals:
            return 30
        if Signal.PURCHASE in signals and det.intent == Intent.APPLICATION:
            return 28
        if Signal.PURCHASE in signals:
            return 25
        if det.intent in (Intent.PRICE, Intent.COVERAGE, Intent.COMPARISON):
            return 18
        if det.intent in (Intent.FAMILY_NEED, Intent.CORPORATE_NEED):
            return 15
        if det.intent == Intent.GENERIC:
            return 5
        return 10

    @staticmethod
    def _readiness_score(det: Detection, signals: set[Signal], text: str) -> int:
        """0-5 exploring, 6-10 comparing, 11-16 asking application, 17-20 ready."""
        if Signal.CONVERSION in signals:
            return 20
        documents = any(k in text for k in ("document", "apply", "sign up", "proceed"))
        payment = any(k in text for k in ("pay", "payment", "how can i pay", "how to pay"))
        if Signal.PURCHASE in signals:
            if documents or payment:
                return 18
            return 14
        if det.intent == Intent.COMPARISON or Signal.COMPETITIVE in signals:
            return 9
        if det.intent in (
            Intent.PRICE, Intent.COVERAGE, Intent.CLAIMS,
            Intent.PAYMENT, Intent.ELIGIBILITY, Intent.WAITING_PERIOD,
        ):
            return 7
        if det.intent in (Intent.FAMILY_NEED, Intent.CORPORATE_NEED):
            return 6
        return 3

    @staticmethod
    def _expansion_score(det: Detection, signals: set[Signal]) -> int:
        """None=0, possible=5, family/upgrade=8-10, multiple/corporate=11-15."""
        if Signal.EXPANSION_CORPORATE in signals:
            return 13
        if Signal.EXPANSION_FAMILY in signals:
            return 10
        if det.intent == Intent.FAMILY_NEED:
            return 5
        return 0

    @staticmethod
    def _engagement_score(opp: Opportunity, text: str) -> int:
        """Low/one-off=0-4, some follow-up=5-8, active=9-12, urgent=13-15."""
        score = min(12, 3 + 2 * opp.turns)
        if any(phrase in text for phrase in _URGENCY_PHRASES):
            score += 3
        return min(15, score)
