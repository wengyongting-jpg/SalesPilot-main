# -*- coding: utf-8 -*-
"""Extraction: reading one customer message into typed observations.

Two implementations, **one protocol**:

    `rules`        deterministic phrase matching. Standard library, no network.
    `model_based`  a model call with an enum-typed structured output.

They are peers, not a primary and a fallback. That framing is the whole correction:
the previous build kept the rule-based classifiers inside an `except Exception:` on
the model path, so the two were never required to agree on anything — and they
diverged until the prompt was offering the model values the domain rejected, silently
disabling three escalation triggers. A declared shared contract is what makes such a
divergence a type error rather than a surprise in production.

Every outcome reports how it was produced and whether anything went wrong, because a
degradation nobody can see is the failure mode being designed out here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol, runtime_checkable

from ...domain.detection import Detection
from ...observability.violations import ModelViolation


@dataclass
class ExtractionOutcome:
    """What was observed, how, and what went wrong on the way.

    `source` is reported on the wire as well: it is the only way a reader can tell
    that an answer advertised as model-driven was in fact produced by a keyword list.
    """

    detection: Detection
    source: str                                  # "llm" | "rules"
    violations: list[ModelViolation] = field(default_factory=list)
    degraded: bool = False
    degradation_reason: Optional[str] = None
    tool_calls: int = 0
    # Whether the degradation is the configured mode rather than a fault: the
    # rule-based peer running because no model is configured. Chooses a log level and
    # nothing else — the outcome still reports `degraded`, because it genuinely did
    # take the other route. Never serialised; `interface-v1.md` is frozen.
    by_design: bool = False

    @property
    def used_a_model(self) -> bool:
        return self.source == "llm"


@runtime_checkable
class Extractor(Protocol):
    """The contract both implementations satisfy."""

    def extract(
        self, text: str, context: Optional[list] = None
    ) -> ExtractionOutcome:
        ...
