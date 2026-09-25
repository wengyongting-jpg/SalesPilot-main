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

import re
from typing import Optional

from ..domain.detection import (
    BuyingPosture, Detection, EvidenceQuality, RetrievalResult, TransactionIssue,
)
from ..domain.decision import Decision, DecisionAction
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
REASON_CANCELLATION = "Policy cancellation requires human handling"
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
REASON_ASSISTANT_PROPOSED = "Assistant proposed handoff"
REASON_READY_TO_PROCEED = "Customer expressed readiness for sales follow-up"
REASON_PAYMENT_REPORTED = "Customer-reported payment requires verification"
REASON_PAYMENT_FAILED = "Payment failure requires staff review"
REASON_PAYMENT_UNCONFIRMED = "Payment was debited without confirmation"
REASON_ORDER_STATUS = "Order or application status requires verification"

_CORPORATE_QUOTE_REQUEST = re.compile(
    r"\b(?:prepare|provide|send|issue|request|need|want|get|give|"
    r"would like)\b.{0,48}\b(?:quote|quotation)\b",
    re.IGNORECASE,
)


def evaluate(
    opp,
    det: Detection,
    retrieval: RetrievalResult,
    *,
    confidence_floor: float = ESCALATE_BELOW_CONFIDENCE,
    customer_text: str = "",
    proposal: Optional[Any] = None,
) -> Optional[str]:
    """Return the escalation reason, or None when the assistant may continue.

    Only genuinely restricted cases escalate. General product questions, requests
    for basic information and ordinary enquiries are answered directly — over-
    escalating is not cautious, it just moves the work to a person who did not need
    to do it.
    """
    from ..domain.detection import HandoffProposal

    signals = set(det.signals)

    # ---- Outside the assistant's authority -------------------------------
    # These fire regardless of qualification. Withholding a complaint from a person
    # because a model suspected advertising would be the worst failure available
    # here: held is not ignored.
    if Signal.HUMAN_REQUEST in signals:
        return REASON_HUMAN_REQUEST

    transaction_reasons = {
        TransactionIssue.PAYMENT_REPORTED: REASON_PAYMENT_REPORTED,
        TransactionIssue.PAYMENT_FAILED: REASON_PAYMENT_FAILED,
        TransactionIssue.PAYMENT_UNCONFIRMED: REASON_PAYMENT_UNCONFIRMED,
        TransactionIssue.ORDER_STATUS: REASON_ORDER_STATUS,
    }
    if det.transaction_issue in transaction_reasons:
        return transaction_reasons[det.transaction_issue]

    if det.intent is Intent.COMPLAINT:
        return REASON_COMPLAINT

    if det.cancellation:
        return REASON_CANCELLATION

    # A price *concern* is hesitation, not a negotiation (P0-1). Only an explicit
    # discount or price-match request lands here, and it says so plainly (P0-4).
    if Signal.NEGOTIATION in signals:
        return REASON_NEGOTIATION

    if Signal.COMPLIANCE_RISK in signals or det.intent is Intent.UNDERWRITING:
        return REASON_UNDERWRITING

    if opp.product is Product.CORPORATE:
        if _CORPORATE_QUOTE_REQUEST.search(customer_text):
            return REASON_CORPORATE_QUOTE
        if det.intent in (
            Intent.CORPORATE_NEED, Intent.PRICE, Intent.APPLICATION,
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

    # ---- Assistant-proposed handoff ----------------------------------------
    # The model can propose a handoff (e.g., customer distress), but it's declined
    # for held conversations or when a person already owns it.
    if proposal and isinstance(proposal, HandoffProposal) and proposal.requested:
        if opp.qualification is not Qualification.QUALIFIED:
            return None
        if opp.human_takeover:
            return None
        return f"{REASON_ASSISTANT_PROPOSED}: {proposal.reason}"

    # Withdrawal is an outcome, not an escalation. Nobody needs to be paged because
    # a customer said no.
    return None


def decide(
    opp,
    det: Detection,
    retrieval: RetrievalResult,
    *,
    confidence_floor: float = ESCALATE_BELOW_CONFIDENCE,
    customer_text: str = "",
    proposal: Optional[Any] = None,
    customer_message_id: Optional[str] = None,
) -> Decision:
    """Return a typed deterministic outcome for service execution.

    `evaluate` remains a compatibility helper for existing kernel clients; the
    conversation service consumes this object and does not infer actions from prose.
    """
    reason = evaluate(
        opp, det, retrieval, confidence_floor=confidence_floor,
        customer_text=customer_text, proposal=proposal,
    )
    if reason:
        return Decision(
            action=DecisionAction.OFFER_HANDOFF,
            reason_code=_reason_code(reason),
            reason=reason,
            restrictions=("withhold_restricted_answer",) if det.restricted else (),
            evidence_message_ids=(customer_message_id,) if customer_message_id else (),
        )
    if det.restricted:
        return Decision(
            action=DecisionAction.HOLD_FOR_STAFF,
            reason_code="restricted_decision",
            reason="The request is outside the assistant's authority",
            restrictions=("withhold_restricted_answer",),
            evidence_message_ids=(customer_message_id,) if customer_message_id else (),
        )
    if (
        det.buying_posture is BuyingPosture.READY_NOW
        and not any(item.quality is EvidenceQuality.CLEAR for item in det.posture_evidence)
    ):
        return Decision(
            action=DecisionAction.CLARIFY,
            reason_code="ready_without_referent",
            reason="Readiness was expressed without a clear next-step referent",
            evidence_message_ids=tuple(dict.fromkeys(
                source_id for evidence in det.posture_evidence
                for source_id in evidence.source_message_ids
            )),
        )
    if det.greeting or det.intent is Intent.GENERIC:
        return Decision(action=DecisionAction.CLARIFY, reason_code="clarify",
                        evidence_message_ids=(customer_message_id,) if customer_message_id else ())
    return Decision(action=DecisionAction.ANSWER, reason_code="answer",
                    evidence_message_ids=(customer_message_id,) if customer_message_id else ())


def _reason_code(reason: str) -> str:
    if reason == REASON_PAYMENT_REPORTED:
        return "payment_reported"
    if reason == REASON_PAYMENT_FAILED:
        return "payment_failed"
    if reason == REASON_PAYMENT_UNCONFIRMED:
        return "payment_unconfirmed"
    if reason == REASON_ORDER_STATUS:
        return "order_status"
    if reason == REASON_HUMAN_REQUEST:
        return "human_request"
    if reason == REASON_COMPLAINT:
        return "complaint"
    if reason in (REASON_UNDERWRITING, REASON_CANCELLATION):
        return "restricted_decision"
    if reason in (REASON_NEGOTIATION, REASON_CORPORATE_QUOTE):
        return "custom_quote"
    if reason == REASON_LOW_CONFIDENCE:
        return "knowledge_gap"
    if reason == REASON_COMPETITIVE:
        return "sales_followup"
    if reason.startswith(REASON_ASSISTANT_PROPOSED):
        return "assistant_proposal"
    return "staff_review"


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
