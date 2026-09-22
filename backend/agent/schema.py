# -*- coding: utf-8 -*-
"""Structured-output models the model is asked to fill in, generated from
`backend.domain.enums` rather than restating the wire strings by hand.

Every field typed as a domain enum makes an out-of-enum value a validation
failure, not a silent downgrade — this is the structural fix for the legacy
defect where the extraction prompt offered `"medical_question"`, a value
`Intent` never accepted, and three escalation triggers went dark with no
error (see `backend/README.md`).

`solicitation` is deliberately absent here: it is the deterministic
corroboration `backend.agent.extraction.rules` always supplies, model or no
model (see `backend/domain/detection.py`), so it is never something we ask
the model to judge.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from ..domain.enums import Intent, Product, Signal


class ExtractionOutput(BaseModel):
    """What the model observes about one customer message.

    Maps onto `backend.domain.detection.Detection`, minus `solicitation`
    (always rule-derived) and minus nothing else — every other field the
    kernel reads is here, typed from the enum that defines it.
    """

    intent: Intent = Field(description="What the customer is asking about.")
    product: Product = Field(
        default=Product.UNKNOWN,
        description="Which CareSure product the message concerns, if any.",
    )
    signals: list[Signal] = Field(
        default_factory=list,
        description="Observable evidence from the message. May be empty.",
    )
    concerns: list[str] = Field(
        default_factory=list,
        description="Short free-text notes on any objection raised (e.g. 'Price').",
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
        default=False, description="True when the customer asks to cancel an existing policy."
    )
    postponement: bool = Field(
        default=False, description="True when the customer asks to defer a decision."
    )
    genuine_enquiry: bool = Field(
        default=True,
        description=(
            "False when this message reads as advertising, a bot, or otherwise "
            "not a prospective customer asking about insurance at all."
        ),
    )
