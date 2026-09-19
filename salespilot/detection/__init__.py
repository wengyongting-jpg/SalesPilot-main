# -*- coding: utf-8 -*-
"""Detection layer: intent, product and sales-signal detection.

Currently keyword-based rules (zero external dependencies, fully offline).
The interfaces are intentionally stable so they can later be replaced with an
LLM / trained classifiers without touching the agent orchestration layer.
"""
from .intent import IntentClassifier
from .product import ProductClassifier
from .signals import SignalDetector
from .llm_extraction import LLMExtractor, ExtractionResult

__all__ = ["IntentClassifier", "ProductClassifier", "SignalDetector", "LLMExtractor", "ExtractionResult"]
