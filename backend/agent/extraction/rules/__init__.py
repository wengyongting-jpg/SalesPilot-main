# -*- coding: utf-8 -*-
"""The rule-based extractor: the offline peer of model-based extraction.

Deterministic, standard library only, no network. This is what runs when no model is
configured, and it is a first-class path rather than a fallback hack — the whole
system completes a conversation on it, which is what makes the demo independent of a
provider being reachable.

It is honest about its own limits in one specific way. `genuine_enquiry` stays true
unless a deterministic solicitation marker fires: a keyword list is not in a position
to judge whether somebody is a real prospective customer, so it does not accuse. The
qualification gate then requires two strikes before acting, which means a rule-based
misjudgement costs a customer nothing.
"""
from __future__ import annotations

from typing import Optional

from ....domain.detection import Detection
from ....domain.enums import Intent, Product, Signal
from .. import ExtractionOutcome
from . import intent as intent_rules
from . import product as product_rules
from . import signals as signal_rules

_RESTRICTED_SIGNALS = frozenset(
    {Signal.HUMAN_REQUEST, Signal.COMPLIANCE_RISK, Signal.NEGOTIATION}
)
_RESTRICTED_INTENTS = frozenset({Intent.UNDERWRITING, Intent.COMPLAINT})


class RuleExtractor:
    """Phrase matching over intent, product and signals."""

    def extract(
        self, text: str, context: Optional[list] = None
    ) -> ExtractionOutcome:
        intent = intent_rules.detect(text, context=context)
        product = product_rules.detect(text, context=context)
        signals, concerns = signal_rules.detect(text, intent, product, context=context)

        solicitation = signal_rules.is_solicitation(text)
        detection = Detection(
            intent=intent,
            product=product,
            signals=signals,
            concerns=concerns,
            restricted=(
                bool(set(signals) & _RESTRICTED_SIGNALS)
                or intent in _RESTRICTED_INTENTS
            ),
            cancellation=signal_rules.is_cancellation(text),
            postponement=signal_rules.is_postponement(text),
            # A keyword list cannot judge genuineness, so it only reports the
            # deterministic marker and leaves the semantic call to a model or,
            # failing that, to the gate's two-strike rule.
            genuine_enquiry=not solicitation,
            solicitation=solicitation,
        )
        return ExtractionOutcome(detection=detection, source="rules")
