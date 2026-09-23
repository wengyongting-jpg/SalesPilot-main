# -*- coding: utf-8 -*-
"""Composing the customer-facing reply.

Two implementations, **one protocol** — the same correction as `extraction`:

    `template`     deterministic wording. Standard library, no network.
    `model_based`  a model call, grounded in the supplied facts.

They are peers. `model_based` does delegate to `template` when a provider fails, but
that is a *declared* degradation between two implementations of one contract, not the
untyped `except Exception:` that let the frozen build's two paths drift apart. The
difference is that the delegation is reported: the outcome says it degraded and why,
and the message it produces is marked `generation="template"` so nobody downstream
believes a model wrote it.

What a composer is given: the approved facts, the customer-safe guidance for the
kernel's reply mode, the customer's own sanitised concern. What it is never given:
the state, the signals, the score, the priority band, or the next best action's
wording. See `docs/backend-plan.md` §3 red line 3.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, runtime_checkable

from ...domain.decision import NextBestAction
from ...domain.enums import Generation
from ...observability.violations import ModelViolation


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
    # What the composing call consumed, for `services` to record. None from the
    # template peer, where there is genuinely nothing to account for.
    usage: Optional[Any] = None
    # Whether the degradation is the configured mode rather than a fault: the template
    # peer composing because no model is configured. Chooses a log level and nothing
    # else. Never serialised; `interface-v1.md` is frozen.
    by_design: bool = False
    disclaimer_appended: bool = False


@runtime_checkable
class Composer(Protocol):
    def compose(self, request: ReplyRequest) -> ReplyOutcome:
        ...
