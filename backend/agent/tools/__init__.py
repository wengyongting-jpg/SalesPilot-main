# -*- coding: utf-8 -*-
"""The tool surface: what the model is allowed to do.

Four read-only knowledge accesses and one proposal channel. Nothing here reaches
`backend.kernel`, and `agent` has no permission to import it — see
`docs/v0.0/backend/backend-plan.md` §3 for why the kernel is a mandatory step executed by
`services` rather than a tool the model may skip, repeat or reorder.

Why these five are safe to expose:

    lookup_product_fact     read-only, idempotent. A missed call produces a weaker
    compare_products        answer, never a corrupted profile.
    list_products
    conversation_summary
    request_human_handoff   writes a *proposal*. `kernel.hitl` reads it as one input
                            among several and decides for itself.

Modelling the handoff as a proposal rather than an action buys something concrete:
the telemetry can show that the model asked for a handover and the kernel declined.
Had the tool opened the case directly, that disagreement would vanish into the
outcome.

The functions take a `ToolContext` explicitly rather than closing over state, so each
is callable — and testable — with no framework and no network.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from ...domain.detection import HandoffProposal
from ...knowledge.loader import KnowledgeBase
from ...observability.violations import ModelViolation


@dataclass
class ToolCall:
    """One tool invocation, recorded for the agent run timeline.

    `interface-v1.md` §1.1 is strict that a tool call means a call the *model chose*
    to make. Fixed pipeline retrieval is not one and must never be counted here.
    """

    name: str
    arguments: dict[str, Any]
    result_chars: int


@dataclass
class ToolContext:
    """Everything the tools may touch, and the record of what they touched.

    Passed as the agent's dependency object. Carrying the recording list here rather
    than in a module-level global is what keeps two concurrent runs from writing into
    each other's timeline.
    """

    kb: KnowledgeBase
    opportunity: Optional[Any] = None
    calls: list[ToolCall] = field(default_factory=list)
    handoff: HandoffProposal = field(default_factory=HandoffProposal)
    question_field: Optional[str] = None
    violations: list[ModelViolation] = field(default_factory=list)

    def record(self, name: str, arguments: dict[str, Any], result: str) -> str:
        self.calls.append(ToolCall(name=name, arguments=arguments, result_chars=len(result)))
        return result

    def coerce(self, raw: Any, enum_cls, field_name: str):
        """Turn a tool argument into an enum member, or report why it could not be.

        Returns `(member, None)` on success and `(None, message)` on failure, where
        the message names the permitted values so the model can correct itself.

        Deliberately not an exception. A hallucinated argument is a normal event with
        a real provider, and letting it propagate aborts the entire run: the first
        version of this code did exactly that, and one bad argument degraded a whole
        extraction to the rule-based peer. Reporting it back as data keeps the run
        alive, keeps the violation visible, and gives the model what it needs to try
        again.
        """
        try:
            return enum_cls(raw), None
        except (ValueError, KeyError):
            permitted = [member.value for member in enum_cls]
            self.violations.append(
                ModelViolation(field=field_name, value=str(raw), allowed=permitted)
            )
            return None, (
                f"{field_name}={raw!r} is not valid. Permitted values: "
                f"{', '.join(permitted)}. Call the tool again with one of these."
            )

    @property
    def call_count(self) -> int:
        return len(self.calls)


# Import tool functions after ToolContext is defined to avoid circular import
from .knowledge import compare_products, list_products, lookup_product_fact
from .handoff import request_human_handoff
from .opportunity import conversation_summary

# Alias for backwards compatibility with tests
get_conversation_summary = conversation_summary
