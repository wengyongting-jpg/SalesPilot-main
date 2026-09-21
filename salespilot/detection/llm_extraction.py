# -*- coding: utf-8 -*-
"""LLM-powered extraction layer.

The LLM is responsible for:
- Understanding conversation context
- Extracting customer intent
- Detecting product interest
- Identifying observable sales signals
- Extracting the main concern

The LLM is NOT responsible for:
- State transitions
- Score calculation
- Priority
- Next best action
- HITL decisions

Those remain in the deterministic backend.

This module falls back to the rule-based classifiers on any LLM error.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Optional

from ..models import Intent, Product, Signal
from .intent import IntentClassifier
from .product import ProductClassifier
from .signals import SignalDetector

_INTENT_VALUES = {e.value for e in Intent}
_PRODUCT_VALUES = {e.value for e in Product}
_SIGNAL_MAP = {s.value: s for s in Signal}

_EXTRACTION_PROMPT = """You are a sales intelligence extractor for CareSure Health Insurance.

Analyse the customer message in the context of the conversation history.

Return ONLY a JSON object with these fields:
{
  "intent": one of ["generic", "price", "coverage", "eligibility", "comparison", "claims", "waiting_period", "payment", "application", "family_need", "corporate_need", "complaint", "human_request", "medical_question"],
  "product": one of ["essential", "family", "plus", "corporate", "unknown"],
  "signals": list of zero or more from ["Purchase", "Hesitation", "Competitive", "Expansion: Family", "Expansion: Corporate", "Human Request", "Compliance Risk"],
  "concern": a short phrase describing the customer's main concern, or empty string if none

Intent definitions:
- generic: general enquiry with no specific intent
- price: asking about premium or cost
- coverage: asking about what is covered
- eligibility: asking about who can apply
- comparison: comparing plans or insurers
- claims: asking about claims process
- waiting_period: asking about waiting periods
- payment: asking about payment methods
- application: asking how to apply or start the policy
- family_need: asking about adding family members
- corporate_need: asking about corporate/employee coverage
- complaint: expressing dissatisfaction
- human_request: explicitly asking to speak to a human
- medical_question: asking about medical/pre-existing conditions

Signal definitions:
- Purchase: customer shows readiness to buy (asks about application, documents, payment, start date)
- Hesitation: customer expresses doubt, price concern, needs time to decide
- Competitive: customer mentions another insurer or asks for comparison
- Expansion: Family: customer asks about adding spouse/child/parent
- Expansion: Corporate: customer asks about employee coverage
- Human Request: customer explicitly asks to speak to a human
- Compliance Risk: personal medical question, underwriting, claim decision, custom quote, negotiation

Return ONLY the JSON. No explanation."""


@dataclass
class ExtractionResult:
    """Result of LLM (or rule-based fallback) extraction."""
    intent: Intent
    product: Product
    signals: list[Signal]
    concerns: list[str]
    restricted: bool = False
    source: str = "rule"  # "llm" or "rule"


class LLMExtractor:
    """Uses an LLM client to extract intent, product, signals, and concern.

    Falls back to rule-based classifiers on any error.
    """

    def __init__(self, llm_client=None) -> None:
        self.llm_client = llm_client
        self._rule_intent = IntentClassifier()
        self._rule_product = ProductClassifier()
        self._rule_signals = SignalDetector()

    def extract(
        self,
        text: str,
        context: Optional[list] = None,
    ) -> ExtractionResult:
        if self.llm_client is None:
            return self._rule_extract(text, context)
        try:
            return self._llm_extract(text, context)
        except Exception:
            return self._rule_extract(text, context)

    def _llm_extract(self, text: str, context: Optional[list]) -> ExtractionResult:
        history = ""
        if context:
            recent = context[-6:]
            for msg in recent:
                role = msg.role if hasattr(msg, "role") else msg.get("role", "")
                content = msg.text if hasattr(msg, "text") else msg.get("text", "")
                history += f"{role}: {content}\n"

        messages = [
            {"role": "system", "content": _EXTRACTION_PROMPT},
            {"role": "user", "content": f"Conversation history:\n{history}\n\nCustomer message: {text}"},
        ]
        raw = self.llm_client.generate(messages, temperature=0.1, max_tokens=400)
        return self._parse_llm_response(raw, text, context)

    def _parse_llm_response(
        self, raw: str, text: str, context: Optional[list]
    ) -> ExtractionResult:
        # Extract JSON from the response (LLMs sometimes wrap in ```json)
        json_match = re.search(r'\{[^{}]*\}', raw, re.DOTALL)
        if not json_match:
            return self._rule_extract(text, context)
        try:
            data = json.loads(json_match.group())
        except json.JSONDecodeError:
            return self._rule_extract(text, context)

        # Parse intent
        intent_str = data.get("intent", "generic")
        intent = Intent(intent_str) if intent_str in _INTENT_VALUES else Intent.GENERIC

        # Parse product
        product_str = data.get("product", "unknown")
        product = Product(product_str) if product_str in _PRODUCT_VALUES else Product.UNKNOWN

        # Parse signals
        signals = []
        for s_str in data.get("signals", []):
            sig = _SIGNAL_MAP.get(s_str)
            if sig and sig not in signals:
                signals.append(sig)

        # Parse concern
        concern = data.get("concern", "").strip()
        concerns = [concern] if concern else []

        # Check restricted (kept in sync with SignalDetector.detect's rule)
        restricted = (
            Signal.HUMAN_REQUEST in signals
            or Signal.COMPLIANCE_RISK in signals
            or Signal.NEGOTIATION in signals
        )

        return ExtractionResult(
            intent=intent,
            product=product,
            signals=signals,
            concerns=concerns,
            restricted=restricted,
            source="llm",
        )

    def _rule_extract(self, text: str, context: Optional[list]) -> ExtractionResult:
        intent = self._rule_intent.detect(text, context=context)
        product = self._rule_product.detect(text, context=context)
        det = self._rule_signals.detect(text, intent, product, context=context)
        return ExtractionResult(
            intent=intent,
            product=product,
            signals=det.signals,
            concerns=det.concerns,
            restricted=det.restricted,
            source="rule",
        )
