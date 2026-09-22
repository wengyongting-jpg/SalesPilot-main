# -*- coding: utf-8 -*-
"""Applying one turn's observations to the opportunity profile.

The profile is the system's long-term memory, and **the kernel writes it, not the
model.** The model contributes typed observations; the rules here decide what enters
the record and how it evolves. A bad model turn can therefore make one turn's
observations wrong, but it cannot poison the memory — which is the material difference
from the common pattern of having a model maintain its own rolling summary, where an
error compounds.

Two high-water marks live here, and they exist for the same reason: a later vague
message must not erase something the conversation already established.

    `best_intent`       the strongest buying intent ever observed
    `urgency_observed`  whether urgency has ever been expressed

The previous build had the first and not the second, so "I need this urgently" was
forgotten one turn later while "I want to apply" was not — the same kind of evidence
treated two different ways.
"""
from __future__ import annotations

from ..domain.detection import Detection
from ..domain.enums import Intent, Signal
from ..domain.opportunity import Opportunity
from . import scoring
from .state_machine import StateTransition


def apply_observations(
    opp: Opportunity,
    det: Detection,
    text: str,
    *,
    transition: StateTransition | None = None,
) -> None:
    """Fold this turn's observations into the profile.

    Mutates `opp`, which is the one place in the kernel that does. Everything else is
    a pure function of its inputs; this is the write step, kept in a single module so
    "what can change the profile" has one answer.
    """
    _accumulate_signals(opp, det)
    _update_flags(opp, det)
    _update_intent(opp, det)
    _update_product(opp, det)

    if det.concerns:
        opp.main_concern = det.concerns[-1]
    if scoring.urgency_in(text):
        opp.urgency_observed = True
    if det.solicitation:
        opp.solicitation_count += 1

    if transition is not None:
        if transition.set_churn_risk:
            opp.churn_risk = True
        if transition.set_expansion and transition.set_expansion not in opp.expansion:
            opp.expansion.append(transition.set_expansion)


def _accumulate_signals(opp: Opportunity, det: Detection) -> None:
    for signal in det.signals:
        if signal not in opp.signal_history:
            opp.signal_history.append(signal)

    # Withdrawal replaces the active set rather than joining it. A customer who has
    # said no is not simultaneously showing purchase intent, and leaving the old
    # signals in place would keep them in the queue on the strength of them.
    if Signal.WITHDRAWAL in det.signals:
        opp.signals = [Signal.WITHDRAWAL]
        return

    for signal in det.signals:
        if signal not in opp.signals:
            opp.signals.append(signal)


def _update_flags(opp: Opportunity, det: Detection) -> None:
    signals = set(det.signals)
    if Signal.COMPETITIVE in signals:
        opp.competitive_risk = True
    if Signal.COMPLIANCE_RISK in signals:
        opp.compliance_risk = True
    if Signal.EXPANSION_FAMILY in signals and "Family" not in opp.expansion:
        opp.expansion.append("Family")
    if Signal.EXPANSION_CORPORATE in signals and "Corporate" not in opp.expansion:
        opp.expansion.append("Corporate")


def _update_intent(opp: Opportunity, det: Detection) -> None:
    opp.last_intent = det.intent
    if scoring.intent_strength(det.intent) >= scoring.intent_strength(opp.best_intent):
        opp.best_intent = det.intent


def _update_product(opp: Opportunity, det: Detection) -> None:
    """Product is sticky.

    Once a conversation is about Plus, a follow-up that names no plan is still about
    Plus. Re-deciding from each message in isolation is what makes an assistant ask
    which plan you meant three times in a row.
    """
    from ..domain.enums import Product

    if det.product is not Product.UNKNOWN:
        opp.product = det.product
