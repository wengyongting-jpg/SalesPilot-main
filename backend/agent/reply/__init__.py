# -*- coding: utf-8 -*-
"""Customer-facing reply composition.

Two peer implementations behind one protocol: `model_based` and `template`. The
template composer marks its output `generation="template"` so a reader is never
misled into thinking a model produced wording that a template did.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Protocol

from ...domain.detection import RetrievalResult
from ...domain.enums import ReplyMode
from ...domain.message import Generation, Message
from ...kernel.next_best_action import NextBestAction
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
from . import model_based as _model_based
from . import template as _template


class TemplateComposer:
    """The offline peer: always available, never calls a model.

    `offline=True` marks the step degraded, for the reason given on
    `extraction.RuleExtractor`: the peer is first class, the *run* is not.
    """

    def __init__(self, *, offline: bool = False) -> None:
        self._offline = offline

    def compose(
        self,
        instruction: str,
        retrieval: RetrievalResult,
        *,
        withdrawal: bool = False,
        takeover: bool = False,
        escalate: bool = False,
        greeting: bool = False,
        recorder: Optional[RunRecorder] = None,
        customer_message: Optional[str] = None,
    ) -> Message:
        return _template.compose(
            retrieval=retrieval,
            withdrawal=withdrawal,
            takeover=takeover,
            escalate=escalate,
            greeting=greeting,
            recorder=recorder,
            degraded_reason=OFFLINE_REASON if self._offline else None,
        )


class ModelComposer:
    """The model-based peer. Falls back to the template peer when the model is
    unavailable, and says so on the run record."""

    def __init__(self, model) -> None:
        self._model = model

    def compose(
        self,
        instruction: str,
        retrieval: RetrievalResult,
        *,
        withdrawal: bool = False,
        takeover: bool = False,
        escalate: bool = False,
        greeting: bool = False,
        recorder: Optional[RunRecorder] = None,
        customer_message: Optional[str] = None,
    ) -> Message:
        return _model_based.compose(
            model=self._model,
            instruction=instruction,
            retrieval=retrieval,
            withdrawal=withdrawal,
            takeover=takeover,
            escalate=escalate,
            greeting=greeting,
            recorder=recorder,
        )


def build_composer(model=None) -> Composer:
    """Build the appropriate composer based on model availability."""
    if model is None:
        return TemplateComposer(offline=True)
    return ModelComposer(model)
