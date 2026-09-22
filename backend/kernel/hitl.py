# -*- coding: utf-8 -*-
"""Human-in-the-loop: when the assistant must hand the conversation to a person.

Escalation exists for two different reasons, and keeping them apart matters:

    outside authority   personalised underwriting or medical assessment, a claim
                        decision, a custom or corporate quotation, a commercial
                        negotiation, a complaint, an explicit request for a person,
                        or retrieval too weak to answer honestly. These escalate
                        whatever the opportunity is worth.

    worth a person      a high-intent opportunity with competitive pressure. This is
                        a *sales* trigger, so it is the one a held conversation must
                        not fire: holding a representative's attention is the cost.

**The reason is load-bearing.** It is what a representative reads before opening the
conversation, so it decides how they prepare. Reporting a discount request as a
medical matter briefs them wrongly, which is why `P0-4` treated that mislabelling as
a correctness bug and not a wording preference.

One active case per opportunity. A new reason while a case is open updates that case
rather than opening a second one, so a queue never shows the same customer twice.
"""
from __future__ import annotations

from typing import Optional

from ..domain.detection import Detection, RetrievalResult
from ..domain.enums import Intent, OpportunityState, Product, Qualification, Signal

# Below this retrieval confidence, a specific question about a known product is
# handed to a person rather than answered from a weak match.
#
# Defined here, not read from `backend.config`, for the same reason `scoring.score`
# takes an injected `now`: the kernel receives its inputs and never reaches out for
# them. A business rule whose outcome depends on an environment variable the module
# read for itself is not reproducible from the stored record. An operator who wants a
# different floor passes one in.
ESCALATE_BELOW_CONFIDENCE = 0.5

# Intents that are factual product questions the assistant may answer directly,
# provided retrieval is confident.
_FACTUAL_INTENTS = {
    Intent.PRICE,
    Intent.COVERAGE,
    Intent.ELIGIBILITY,
    Intent.CLAIMS,
    Intent.WAITING_PERIOD,
    Intent.PAYMENT,
    Intent.COMPARISON,
}

REASON_HUMAN_REQUEST = "Customer explicitly asked to speak to a person"
REASON_COMPLAINT = "Complaint handling is outside the assistant's authority"
REASON_NEGOTIATION = (
    "Commercial negotiation or discount request requires human handling"
)
REASON_UNDERWRITING = (
    "Personalised medical or underwriting question requires human assessment"
)
REASON_CORPORATE_QUOTE = "Corporate quotation requires human handling"
REASON_LOW_CONFIDENCE = "Retrieval too weak to answer — do not guess"
REASON_COMPETITIVE = (
    "High purchase intent with competitive comparison — recommend human sales "
    "intervention"
)


def evaluate(
    opp,
    det: Detection,
    retrieval: RetrievalResult,
    *,
    confidence_floor: float = ESCALATE_BELOW_CONFIDENCE,
) -> Optional[str]:
    """Return the escalation reason, or None when the assistant may continue.

    Only genuinely restricted cases escalate. General product questions, requests
    for basic information and ordinary enquiries are answered directly — over-
    escalating is not cautious, it just moves the work to a person who did not need
    to do it.
    """
    signals = set(det.signals)

    # ---- Outside the assistant's authority -------------------------------
    # These fire regardless of qualification. Withholding a complaint from a person
    # because a model suspected advertising would be the worst failure available
    # here: held is not ignored.
    if Signal.HUMAN_REQUEST in signals:
        return REASON_HUMAN_REQUEST

    if det.intent is Intent.COMPLAINT:
        return REASON_COMPLAINT

    # A price *concern* is hesitation, not a negotiation (P0-1). Only an explicit
    # discount or price-match request lands here, and it says so plainly (P0-4).
    if Signal.NEGOTIATION in signals:
        return REASON_NEGOTIATION

    if Signal.COMPLIANCE_RISK in signals or det.intent is Intent.UNDERWRITING:
        return REASON_UNDERWRITING

    if opp.product is Product.CORPORATE and det.intent in (
        Intent.CORPORATE_NEED,
        Intent.PRICE,
    ) and Signal.PURCHASE in signals:
        return REASON_CORPORATE_QUOTE

    # Weak retrieval, but only for a specific question about a known product. A
    # generic enquiry with no match is answered generally, not escalated.
    if (
        opp.product is not Product.UNKNOWN
        and det.intent in _FACTUAL_INTENTS
        and retrieval.confidence < confidence_floor
    ):
        return REASON_LOW_CONFIDENCE

    # ---- Worth a person --------------------------------------------------
    # A sales trigger, so it is gated on qualification and on takeover not already
    # being in force.
    if (
        opp.qualification is Qualification.QUALIFIED
        and opp.state is OpportunityState.HIGH_INTENT
        and (Signal.COMPETITIVE in signals or opp.competitive_risk)
        and not opp.human_takeover
    ):
        return REASON_COMPETITIVE

    # Withdrawal is an outcome, not an escalation. Nobody needs to be paged because
    # a customer said no.
    return None


def summarise(opp) -> str:
    """The handover briefing a representative reads.

    Deliberately a plain sentence rather than a field dump: it is read under time
    pressure, next to a queue of other cases.
    """
    signals = ", ".join(signal.value for signal in opp.signals) or "-"
    product = opp.product.value if opp.product is not Product.UNKNOWN else "unknown"
    return (
        f"Customer is in state '{opp.state.value}' interested in {product}. "
        f"Signals: {signals}. Main concern: {opp.main_concern or '-'}. "
        f"Competitive risk: {'yes' if opp.competitive_risk else 'none'}. "
        f"Expansion: {', '.join(opp.expansion) if opp.expansion else 'none'}."
    )
