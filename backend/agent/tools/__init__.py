# -*- coding: utf-8 -*-
"""The tool surface: what the model is allowed to do.

Signatures and argument types derive from `backend.domain.enums`, so a tool call
carrying a value the domain rejects fails validation instead of being coerced.

`request_human_handoff` only *proposes* an escalation. `backend.kernel.hitl`
decides. The model cannot open a case, move a state or change a score.

These are plain functions with no `pydantic_ai` dependency, so they are
directly unit-testable. `agent/runtime.py` wraps them as tools on a
`pydantic_ai.Agent` at run time, closing `get_conversation_summary` over that
run's transcript rather than exposing the transcript as a model-supplied
argument.
"""
from __future__ import annotations

from .handoff import request_human_handoff
from .knowledge import compare_products, list_products, lookup_product_fact
from .opportunity import get_conversation_summary

__all__ = [
    "compare_products",
    "get_conversation_summary",
    "list_products",
    "lookup_product_fact",
    "request_human_handoff",
]
