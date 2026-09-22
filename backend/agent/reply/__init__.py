# -*- coding: utf-8 -*-
"""Customer-facing reply composition.

Two peer implementations behind one protocol: `model_based` and `template`. The
template composer marks its output `generation="template"` so a reader is never
misled into thinking a model produced wording that a template did.
"""
from __future__ import annotations

from typing import Any, Optional, Protocol

from ...domain.detection import RetrievalResult
from ...domain.message import Message
from ...observability import RunRecorder
from . import template as _template

STEP_NAME = "response_generation"


class Composer(Protocol):
    def compose(
        self,
        instruction: str,
        retrieval: RetrievalResult,
        *,
        withdrawal: bool = False,
        takeover: bool = False,
        escalate: bool = False,
        recorder: Optional[RunRecorder] = None,
        message_history: Optional[list[Any]] = None,
    ) -> Message: ...


class TemplateComposer:
    """The offline peer: always available, never calls a model."""

    def compose(
        self,
        instruction: str,
        retrieval: RetrievalResult,
        *,
        withdrawal: bool = False,
        takeover: bool = False,
        escalate: bool = False,
        recorder: Optional[RunRecorder] = None,
        message_history: Optional[list[Any]] = None,
    ) -> Message:
        return _template.compose(
            retrieval=retrieval,
            withdrawal=withdrawal,
            takeover=takeover,
            escalate=escalate,
            recorder=recorder,
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
        recorder: Optional[RunRecorder] = None,
        message_history: Optional[list[Any]] = None,
    ) -> Message:
        # Withdrawal/takeover/escalation replies are never model-generated —
        # they are deterministic holding messages regardless of provider, the
        # one part of the frozen build's design this rebuild keeps unchanged.
        if withdrawal or takeover or escalate:
            return _template.compose(
                retrieval=retrieval,
                withdrawal=withdrawal,
                takeover=takeover,
                escalate=escalate,
                recorder=recorder,
            )
        from . import model_based

        return model_based.compose(
            instruction,
            retrieval,
            model=self._model,
            recorder=recorder,
            message_history=message_history,
        )


def build_composer(model=None) -> Composer:
    """`model=None` selects the offline (template) peer."""
    if model is None:
        return TemplateComposer()
    return ModelComposer(model)
