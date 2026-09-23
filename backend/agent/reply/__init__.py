# -*- coding: utf-8 -*-
"""Customer-facing reply composition.

Two peer implementations behind one protocol: `model_based` and `template`. The
template composer marks its output `generation="template"` so a reader is never
misled into thinking a model produced wording that a template did.
"""
from __future__ import annotations

from typing import Optional, Protocol

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
        greeting: bool = False,
        recorder: Optional[RunRecorder] = None,
        customer_message: Optional[str] = None,
    ) -> Message: ...


OFFLINE_REASON = "no model configured — template reply"


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
        # Withdrawal/takeover/escalation replies are never model-generated —
        # they are deterministic holding messages regardless of provider, the
        # one part of the frozen build's design this rebuild keeps unchanged.
        # A greeting is deliberately not in this list: it is not
        # safety-sensitive, so a configured model composes it from
        # `instruction` (already framed as "just greet, don't enumerate
        # facts" by `policy.customer_safe_projection`) instead of being
        # forced to the fixed template — this is where a model's own
        # conversational range is worth using.
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
            greeting=greeting,
            customer_message=customer_message,
        )


def build_composer(model=None) -> Composer:
    """`model=None` selects the offline (template) peer, and says so on the record."""
    if model is None:
        return TemplateComposer(offline=True)
    return ModelComposer(model)
