# -*- coding: utf-8 -*-
"""Rule-based classifiers: the offline peer of model-based extraction.

Deterministic, standard library only, no network. This is what runs when no
model is configured, and it is a first-class path rather than a fallback hack.
"""
from __future__ import annotations

from typing import Optional

from ....domain.detection import Detection
from ....domain.message import Message
from . import intent as _intent
from . import product as _product
from . import signals as _signals


def extract(text: str, context: Optional[list[Message]] = None) -> Detection:
    """The rule-based peer of `extraction.model_based.extract`: same shape, no model."""
    detected_intent = _intent.detect(text, context)
    detected_product = _product.detect(text, context)
    observed = _signals.detect(text, detected_intent, detected_product, context)
    return Detection(
        intent=detected_intent,
        product=detected_product,
        signals=observed.signals,
        concerns=observed.concerns,
        restricted=observed.restricted,
        cancellation=observed.cancellation,
        postponement=observed.postponement,
        # A keyword list judges "is this advertising" reasonably (solicitation,
        # below) but judges "is this a genuine enquiry" badly — see
        # `backend/domain/detection.py`. The rule-based peer stays at the
        # default (True) here rather than guessing.
        genuine_enquiry=True,
        solicitation=observed.solicitation,
    )
