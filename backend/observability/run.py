# -*- coding: utf-8 -*-
"""The agent run record: what the agent did, and whether any of it went wrong.

Wire shape: `docs/api/interface-v1.md` §5.3. Admin tier only — under §2 the customer
response has no shape for any of this.

`status` carries the distinction the whole package exists for:

    ok          everything ran as intended
    degraded    a step produced a usable result by a worse route. Two causes, and the
                record keeps them apart: the model was unavailable, or the model was
                wrong. The second was invisible in the previous build.
    error       an exception. A bug, not a provider hiccup.

An error outranks a degradation when the run is summarised, because a reader who sees
"degraded" will look at the provider, and a reader who sees "error" will look at the
code. Sending them to the wrong place is the cost of blurring the two.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

from .pricing import Money, zero
from .violations import ModelViolation


class RunStatus(str, Enum):
    OK = "ok"
    DEGRADED = "degraded"
    ERROR = "error"

    @property
    def severity(self) -> int:
        return {"ok": 0, "degraded": 1, "error": 2}[self.value]


class StepKind(str, Enum):
    """What kind of work a step was.

    `TOOL` is reserved for a call the **model chose** to make. Fixed pipeline
    retrieval is `RETRIEVAL` and must never be counted as a tool call — see
    `interface-v1.md` §1.1 rule 2, which exists because inflating that number is an
    easy way to make a dashboard look more agentic than the system is.
    """

    LLM = "llm"
    RULE = "rule"
    RETRIEVAL = "retrieval"
    TOOL = "tool"


@dataclass
class Content:
    """A prompt or a model output: always its length, sometimes its text.

    `chars` is the **true** length even when the text is withheld or truncated, so a
    reader can tell that something was cut rather than that it was short.
    """

    chars: int
    content: Optional[str] = None

    def to_dict(self) -> dict:
        return {"chars": self.chars, "content": self.content}


@dataclass
class RunStep:
    index: int
    name: str
    kind: StepKind
    duration_ms: int
    status: RunStatus = RunStatus.OK
    detail: Optional[str] = None
    # Whether a degradation is the configured mode rather than a fault. **Not
    # serialised**: `interface-v1.md` is frozen, so no field may be added to the wire.
    # This exists only to choose a log level - see `logging._level_for`.
    by_design: bool = False

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "name": self.name,
            "kind": self.kind.value,
            "duration_ms": self.duration_ms,
            "status": self.status.value,
            "detail": self.detail,
        }


@dataclass
class LlmCall:
    index: int
    purpose: str
    model: str
    duration_ms: int
    prompt_tokens: int
    completion_tokens: int
    cost: Money
    input: Content
    output: Content

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "purpose": self.purpose,
            "model": self.model,
            "duration_ms": self.duration_ms,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "cost": self.cost.to_dict(),
            "input": self.input.to_dict(),
            "output": self.output.to_dict(),
        }


@dataclass
class ToolCallRecord:
    """A call the model chose to make."""

    index: int
    name: str
    arguments: dict
    result_chars: int

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "name": self.name,
            "arguments": self.arguments,
            "result_chars": self.result_chars,
        }


@dataclass
class AgentRun:
    opportunity_id: str
    run_id: str = field(default_factory=lambda: f"ar-{uuid.uuid4().hex[:8]}")
    client_message_id: Optional[str] = None
    trigger: str = "customer_message"
    customer_message_count: int = 0
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    duration_ms: int = 0
    status: RunStatus = RunStatus.OK
    steps: list[RunStep] = field(default_factory=list)
    llm_calls: list[LlmCall] = field(default_factory=list)
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    violations: list[ModelViolation] = field(default_factory=list)

    # ---- Derived totals -------------------------------------------------

    @property
    def degraded_by_design(self) -> bool:
        """True when this run degraded only in ways that were the configured mode.

        The distinction the log level needs. Running with no model configured degrades
        every run — that is the documented default, not a fault, and reporting each one
        at WARNING means the default mode looks broken and real warnings are buried in
        a stream of expected ones.

        Deliberately **all** rather than **any**: one genuine fault in a run makes the
        whole run worth a warning, even alongside expected offline degradations.
        """
        degraded = [step for step in self.steps if step.status is RunStatus.DEGRADED]
        return bool(degraded) and all(step.by_design for step in degraded)

    @property
    def total_tokens(self) -> int:
        return sum(call.total_tokens for call in self.llm_calls)

    @property
    def total_cost(self) -> Money:
        total = zero()
        for call in self.llm_calls:
            total = total + call.cost
        return total

    @property
    def models_used(self) -> list[str]:
        seen: list[str] = []
        for call in self.llm_calls:
            if call.model not in seen:
                seen.append(call.model)
        return seen

    def totals(self) -> dict:
        return {
            "agent_step_count": len(self.steps),
            "llm_call_count": len(self.llm_calls),
            # Model-selected calls only.
            "tool_call_count": len(self.tool_calls),
            "total_tokens": self.total_tokens,
            "cost": self.total_cost.to_dict(),
        }

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "opportunity_id": self.opportunity_id,
            "client_message_id": self.client_message_id,
            "trigger": self.trigger,
            "customer_message_count": self.customer_message_count,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "duration_ms": self.duration_ms,
            "status": self.status.value,
            "steps": [step.to_dict() for step in self.steps],
            "llm_calls": [call.to_dict() for call in self.llm_calls],
            "tool_calls": [call.to_dict() for call in self.tool_calls],
            "violations": [
                {
                    "field": violation.field,
                    "value": violation.value,
                    "allowed": violation.allowed,
                    "message": violation.message,
                }
                for violation in self.violations
            ],
            "totals": self.totals(),
        }
