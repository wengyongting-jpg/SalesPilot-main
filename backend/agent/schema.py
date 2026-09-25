# -*- coding: utf-8 -*-
"""The structured output the model must produce, typed by the domain enums.

**Generated from `backend.domain.enums`, not restated from it.** That distinction is
the entire point of this module. In the previous build the extraction prompt and the
domain enums were two hand-maintained copies of one truth, and they drifted: the
prompt offered `"medical_question"` where the domain defined `"underwriting"`, and
listed seven of the eleven signals. Three escalation triggers became unreachable
whenever a model was configured. Nothing in the code prevented it, so it happened.

Here the enum *is* the type. Adding a signal to `domain.enums.Signal` changes what
the model is offered, what the schema validates and what the prompt lists, in one
edit, with no opportunity to update two of the three.

Two paths out of a model response:

    `ExtractionOutput`  the strict model. The framework generates a JSON schema from
                        it, so the model is told the exact permitted values and a bad
                        one fails validation.

    `parse`             the lenient path, for a raw payload that has already come back
                        wrong. It records a `ModelViolation` naming the offending
                        value and falls back — the fallback is never silent, which is
                        the behaviour the old build lacked.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from ..domain.detection import (
    BuyingPosture, Detection, EvidenceQuality, ObservationEvidence,
    TransactionIssue,
)
from ..domain.enums import Intent, Product, Signal
from ..observability.violations import ModelViolation


class ExtractionOutput(BaseModel):
    """What the model returns after reading one customer message.

    Every field is an observation. None of them is a decision: the state, the score,
    the priority, the next best action and the escalation are all derived from these
    by `backend.kernel`, which the model cannot reach.
    """

    intent: Intent = Field(
        default=Intent.GENERIC,
        description="What the customer is asking about.",
    )
    product: Product = Field(
        default=Product.UNKNOWN,
        description="Which plan the message is about, or unknown.",
    )
    signals: list[Signal] = Field(
        default_factory=list,
        description="Observable sales evidence present in this message.",
    )
    concerns: list[str] = Field(
        default_factory=list,
        description="Short free-text notes on objections raised (e.g. 'Price', 'Coverage gaps').",
    )
    genuine_enquiry: bool = Field(
        default=True,
        description=(
            "False when the message is not a prospective customer enquiry at all — "
            "advertising, a bot, or unrelated to insurance."
        ),
    )
    solicitation: bool = Field(
        default=False,
        description=(
            "True when the sender is offering or promoting something to us rather "
            "than asking about cover."
        ),
    )
    restricted: bool = Field(
        default=False,
        description=(
            "True when the message touches something outside the assistant's "
            "authority: personalised medical/underwriting judgement, a claim "
            "decision, a custom quotation, or an explicit request for a person."
        ),
    )
    cancellation: bool = Field(
        default=False,
        description="True when the customer wants to cancel an existing policy.",
    )
    postponement: bool = Field(
        default=False,
        description="True when the customer is explicitly deferring a decision.",
    )
    buying_posture: BuyingPosture = Field(
        default=BuyingPosture.UNKNOWN,
        description=(
            "The customer's current buying posture, based on their latest explicit "
            "position. Asking an application-process question alone is browsing."
        ),
    )
    posture_evidence: str = Field(
        default="",
        description=(
            "A short exact supporting span from the latest customer message; empty "
            "when posture is unknown. Do not invent or paraphrase evidence."
        ),
    )
    posture_evidence_quality: EvidenceQuality = Field(
        default=EvidenceQuality.UNKNOWN,
        description="Quality of the exact posture span: clear, ambiguous, or unknown.",
    )
    transaction_issue: TransactionIssue = Field(
        default=TransactionIssue.NONE,
        description=(
            "A customer-reported payment or order status that requires verification. "
            "Use none for general questions about payment methods. A customer claim "
            "does not verify that payment or policy activation occurred."
        ),
    )
    transaction_evidence: str = Field(
        default="",
        description="Exact supporting words from the latest customer message; never paraphrase.",
    )
    transaction_evidence_quality: EvidenceQuality = Field(
        default=EvidenceQuality.UNKNOWN,
        description="Use clear only when the exact span explicitly states the transaction issue.",
    )


def allowed_values() -> dict[str, list[str]]:
    """The permitted values, read off the enums.

    The single source for the prompt, for documentation and for violation messages.
    Nothing else may hand-write these lists.
    """
    return {
        "intent": [member.value for member in Intent],
        "product": [member.value for member in Product],
        "signals": [member.value for member in Signal],
        "buying_posture": [member.value for member in BuyingPosture],
        "posture_evidence_quality": [member.value for member in EvidenceQuality],
        "transaction_issue": [member.value for member in TransactionIssue],
    }


def to_detection(output: ExtractionOutput) -> Detection:
    """Convert the model's output to a Detection domain object."""
    return Detection(
        intent=output.intent,
        product=output.product,
        signals=output.signals,
        concerns=output.concerns,
        genuine_enquiry=output.genuine_enquiry,
        solicitation=output.solicitation,
        restricted=output.restricted,
        cancellation=output.cancellation,
        postponement=output.postponement,
        buying_posture=output.buying_posture,
        posture_evidence=(
            [ObservationEvidence(span=output.posture_evidence, quality=output.posture_evidence_quality)]
            if output.posture_evidence and output.buying_posture is not BuyingPosture.UNKNOWN
            else []
        ),
        transaction_issue=output.transaction_issue,
        transaction_evidence=(
            [ObservationEvidence(span=output.transaction_evidence,
                                 quality=output.transaction_evidence_quality)]
            if output.transaction_evidence and output.transaction_issue is not TransactionIssue.NONE
            else []
        ),
    )


def parse(payload: dict, *, customer_text: str = "") -> tuple[Detection, list[ModelViolation]]:
    """Lenient parse that records violations and falls back.

    Used for a raw payload that has already come back wrong — a value outside the
    schema is recorded as a `ModelViolation` naming the offending field and value
    (never silent) and a safe fallback is substituted, so the turn is never lost
    over one bad field.
    """
    violations: list[ModelViolation] = []

    intent_str = payload.get("intent", Intent.GENERIC.value)
    try:
        intent = Intent(intent_str)
    except ValueError:
        violations.append(
            ModelViolation(field="intent", value=str(intent_str), allowed=[m.value for m in Intent])
        )
        intent = Intent.GENERIC

    product_str = payload.get("product", Product.UNKNOWN.value)
    try:
        product = Product(product_str)
    except ValueError:
        violations.append(
            ModelViolation(field="product", value=str(product_str), allowed=[m.value for m in Product])
        )
        product = Product.UNKNOWN

    signals: list[Signal] = []
    for raw in payload.get("signals", []):
        try:
            signals.append(Signal(raw))
        except ValueError:
            violations.append(
                ModelViolation(field="signals", value=str(raw), allowed=[m.value for m in Signal])
            )

    concerns = payload.get("concerns")
    if concerns is None:
        single = payload.get("concern")
        concerns = [single] if single else []

    detection = Detection(
        intent=intent,
        product=product,
        signals=signals,
        concerns=concerns,
        genuine_enquiry=payload.get("genuine_enquiry", True),
        solicitation=payload.get("solicitation", False),
        restricted=payload.get("restricted", False),
        cancellation=payload.get("cancellation", False),
        postponement=payload.get("postponement", False),
        buying_posture=BuyingPosture(payload.get("buying_posture", BuyingPosture.UNKNOWN.value)),
        posture_evidence=(
            [ObservationEvidence(
                span=str(payload["posture_evidence"]),
                quality=EvidenceQuality(payload.get("posture_evidence_quality", EvidenceQuality.UNKNOWN.value)),
            )]
            if payload.get("posture_evidence") else []
        ),
        transaction_issue=TransactionIssue(
            payload.get("transaction_issue", TransactionIssue.NONE.value)
        ),
        transaction_evidence=(
            [ObservationEvidence(
                span=str(payload["transaction_evidence"]),
                quality=EvidenceQuality(payload.get(
                    "transaction_evidence_quality", EvidenceQuality.UNKNOWN.value
                )),
            )]
            if payload.get("transaction_evidence") else []
        ),
    )
    return detection, violations
