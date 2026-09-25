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
    # The customer's own latest message, verbatim. `concern` is a coarse
    # category ("Price", "Competitor", ...) set only when a specific signal
    # fired, and `history` (below) excludes the current turn - without this,
    # fact selection had nothing telling it what was actually asked, and
    # would have to select against the facts alone.
    customer_text: str = ""
    disclaimer: str = ""
    # The observing segment's message history, so the composing segment continues
    # one conversation instead of starting a second one.
    history: Optional[list] = None
    # Sourced recall notes help interpret references when the transcript is long.
    # They are explicitly unverified and may never be used as product/order facts.
    memory: Optional[dict] = None
    # Model selections are identifiers from a mode-specific allowlist. The renderer
    # ignores any value outside that allowlist and uses the deterministic default.
    template_id: Optional[str] = None
    acknowledgement_id: str = "none"
    usage_limits: object = None
    model_allowed: bool = True
    model_budget_reason: Optional[str] = None
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
    # The approved facts actually rendered in this reply. Retrieval can offer
    # more than the model selects, and fixed/standalone replies show none.
    displayed_facts: list[str] = field(default_factory=list)
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
