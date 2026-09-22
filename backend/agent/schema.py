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

from ..domain.detection import Detection
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
    concern: str = Field(
        default="",
        description="The customer's main concern in a short phrase, or empty.",
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
    cancellation: bool = Field(
        default=False,
        description="True when the customer wants to cancel an existing policy.",
    )
    postponement: bool = Field(
        default=False,
        description="True when the customer is explicitly deferring a decision.",
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
    }


def to_detection(output: ExtractionOutput) -> Detection:
    concern = output.concern.strip()
    return Detection(
        intent=output.intent,
        product=output.product,
        signals=list(output.signals),
        concerns=[concern] if concern else [],
        restricted=_is_restricted(output.signals, output.intent),
        cancellation=output.cancellation,
        postponement=output.postponement,
        genuine_enquiry=output.genuine_enquiry,
        solicitation=output.solicitation,
    )


def parse(payload: dict) -> tuple[Detection, list[ModelViolation]]:
    """Read a raw model payload, recording anything the domain rejects.

    Used when a response arrives outside the strict schema — a provider without
    structured-output support, or a validation retry that still came back wrong.
    Every substitution produces a violation, because an unrecorded downgrade is
    exactly the defect this rebuild exists to remove.
    """
    violations: list[ModelViolation] = []
    permitted = allowed_values()

    intent = _coerce(
        payload.get("intent"), Intent, "intent", permitted["intent"], violations,
        default=Intent.GENERIC,
    )
    product = _coerce(
        payload.get("product"), Product, "product", permitted["product"], violations,
        default=Product.UNKNOWN,
    )

    signals: list[Signal] = []
    for raw in payload.get("signals") or []:
        signal = _coerce(
            raw, Signal, "signals", permitted["signals"], violations, default=None
        )
        if signal is not None and signal not in signals:
            signals.append(signal)

    concern = str(payload.get("concern") or "").strip()

    return (
        Detection(
            intent=intent,
            product=product,
            signals=signals,
            concerns=[concern] if concern else [],
            restricted=_is_restricted(signals, intent),
            cancellation=bool(payload.get("cancellation", False)),
            postponement=bool(payload.get("postponement", False)),
            genuine_enquiry=bool(payload.get("genuine_enquiry", True)),
            solicitation=bool(payload.get("solicitation", False)),
        ),
        violations,
    )


def _coerce(raw, enum_cls, field_name, permitted, violations, *, default):
    """Turn a raw value into an enum member, or record why it could not be."""
    if raw is None:
        return default
    try:
        return enum_cls(raw)
    except ValueError:
        violations.append(
            ModelViolation(field=field_name, value=str(raw), allowed=list(permitted))
        )
        return default


def _is_restricted(signals, intent) -> bool:
    """Whether the message touches something outside the assistant's authority.

    Derived here rather than trusted from the model: it decides whether a reply is
    allowed at all, so it is not a judgement to delegate.
    """
    restricted_signals = {
        Signal.HUMAN_REQUEST, Signal.COMPLIANCE_RISK, Signal.NEGOTIATION,
    }
    return bool(set(signals) & restricted_signals) or intent in (
        Intent.UNDERWRITING, Intent.COMPLAINT,
    )
