# -*- coding: utf-8 -*-
"""Extraction of intent, product, signals and concern from a customer message.

Two peer implementations behind one protocol: `model_based` and `rules`. They
are peers, not a primary and a patch. The original build kept the rule-based
classifiers as an exception handler and the two drifted until the prompt offered
the model enum values the domain did not accept -- a defect that silently
disabled three HITL triggers. A declared shared contract is the fix.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional, Protocol, runtime_checkable

from ...domain.detection import Detection, HandoffProposal
from ...domain.message import Message
from ...observability import RunRecorder
from ...observability.violations import ModelViolation


@dataclass
class ExtractionOutcome:
    """What one extraction call produced, and how.

    `source`, `violations` and `unavailable` exist so a caller (eventually
    `services`) can report a degraded run without inspecting the detection for
    clues -- exactly the distinction `docs/backend-plan.md` §7 draws between
    "model unavailable" (`unavailable`) and "model wrong" (`violations`).

    `handoff` is the model's proposal, if it made one; the kernel decides.
    `trace` is the framework's own message list from a model run, kept opaque
    here so the reply peer can continue the same conversation.
    """

    detection: Detection
    source: Literal["llm", "rules"]
    violations: list[ModelViolation] = field(default_factory=list)
    unavailable: Optional[str] = None
    handoff: Optional[HandoffProposal] = None
    trace: list[Any] = field(default_factory=list)


@runtime_checkable
class Extractor(Protocol):
    def extract(
        self,
        text: str,
        context: Optional[list[Message]] = None,
        *,
        recorder: Optional[RunRecorder] = None,
    ) -> ExtractionOutcome: ...


# Import rules module AFTER ExtractionOutcome is defined to avoid circular import
from . import rules


OFFLINE_REASON = "no model configured — rule-based extraction"


class RuleExtractor:
    """The offline peer: always available, never calls a model.

    `offline=True` marks the step degraded. The implementation is a first-class
    peer, not a stub — but a *run* that never reached a model did not run at
    full capability, and `interface-v1.md` §5.7 requires that to be visible
    rather than indistinguishable from a model-backed run.
    """

    def __init__(self, *, offline: bool = False) -> None:
        self._offline = offline

    def extract(
        self,
        text: str,
        context: Optional[list[Message]] = None,
        *,
        recorder: Optional[RunRecorder] = None,
    ) -> ExtractionOutcome:
        if recorder is None:
            return ExtractionOutcome(detection=rules.extract(text, context), source="rules")
        with recorder.step("extraction", "rule") as step:
            detection = rules.extract(text, context)
            if self._offline:
                step.degrade(OFFLINE_REASON)
            else:
                step.note(f"intent={detection.intent.value} product={detection.product.value}")
        return ExtractionOutcome(
            detection=detection,
            source="rules",
            unavailable=OFFLINE_REASON if self._offline else None,
        )


class ModelExtractor:
    """The model-based peer. Falls back to the rule peer when the model is
    unavailable or wrong, and says which."""

    def __init__(self, model) -> None:
        self._model = model

    def extract(
        self,
        text: str,
        context: Optional[list[Message]] = None,
        *,
        recorder: Optional[RunRecorder] = None,
    ) -> ExtractionOutcome:
        from . import model_based

        return model_based.extract(text, context, model=self._model, recorder=recorder)


def build_extractor(model=None) -> Extractor:
    """`model=None` selects the offline (rule-based) peer, and says so on the record."""
    if model is None:
        return RuleExtractor(offline=True)
    return ModelExtractor(model)
