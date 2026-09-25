# -*- coding: utf-8 -*-
"""Customer-facing reply composition.

Two peer implementations behind one protocol: `model_based` and `template`. The
template composer marks its output `generation="template"` so a reader is never
misled into thinking a model produced wording that a template did.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Protocol

from ...domain.decision import NextBestAction
from ...domain.detection import RetrievalResult
from ...domain.enums import ReplyMode
from ...domain.message import Generation, Message
from ...observability import RunRecorder
from ...observability.violations import ModelViolation

STEP_NAME = "response_generation"


@dataclass
class ReplyRequest:
    """Everything a composer may see. Deliberately a closed list."""
    facts: list[str]
    action: NextBestAction
    customer_name: str = ""
    concern: Optional[str] = None
    disclaimer: str = ""
    # The observing segment's message history, so the composing segment continues
    # one conversation instead of starting a second one.
    history: Optional[list] = None
    # False for a pre-curated enumeration (e.g. "what plans are there?" - one
    # short line per product, already trimmed to what's worth showing) where
    # every fact belongs in the answer. Model-based fact selection exists to
    # pick a few relevant fields out of a larger pool for *one* product; run
    # against an enumeration, it instead drops most of the products, which
    # answers a different question than the one asked.
    select_facts: bool = True


@dataclass
class ReplyOutcome:
    text: str
    generation: Generation
    degraded: bool = False
    degradation_reason: Optional[str] = None
    violations: list[ModelViolation] = field(default_factory=list)
    history: list[Any] = field(default_factory=list)
    by_design: bool = False
    usage: dict[str, Any] = field(default_factory=dict)


class Composer(Protocol):
    def compose(self, request: ReplyRequest) -> ReplyOutcome: ...


OFFLINE_REASON = "no model configured — template reply"


# Import after dataclass definitions to avoid circular import
from .model_based import ModelComposer
from .template import TemplateComposer


def build_composer(model=None) -> Composer:
    """Build the appropriate composer based on model availability."""
    if model is None:
        return TemplateComposer()
    return ModelComposer(model)
