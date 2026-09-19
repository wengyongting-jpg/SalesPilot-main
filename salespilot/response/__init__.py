# -*- coding: utf-8 -*-
"""Response generation layer: rule-based template and optional LLM backend."""
from .generator import ResponseGenerator
from .llm_generator import LLMResponseGenerator

__all__ = ["ResponseGenerator", "LLMResponseGenerator"]
