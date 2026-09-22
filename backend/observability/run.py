# -*- coding: utf-8 -*-
"""The agent run record: `interface-v1.md` §5.3, field for field.

Plain dataclasses, standard library only. Nothing here knows about the agent
framework — `backend.agent.telemetry` translates framework objects into these
types, so the record shape stays stable if the framework is ever replaced.

`totals` is computed from the parts, never stored, so it cannot disagree with
them. `status` is derived from the steps for the same reason.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Literal, Optional

StepKind = Literal["llm", "rule", "retrieval", "tool"]
Status = Literal["ok", "degraded", "error"]


@dataclass(frozen=True)
class Cost:
    amount: Decimal
    currency: str = "USD"

    def to_dict(self) -> dict:
        return {"amount": float(round(self.amount, 6)), "currency": self.currency}


@dataclass(frozen=True)
class Content:
    """Length is always reported; the text itself may be withheld (`None`)."""

    chars: int
    content: Optional[str] = None

    def to_dict(self) -> dict:
        payload: dict = {"chars": self.chars}
        if self.content is not None:
            payload["content"] = self.content
        return payload


@dataclass
class LlmCall:
    index: int
    purpose: str
    model: str
    duration_ms: int
    prompt_tokens: int
    completion_tokens: int
    input: Content
    output: Content
    cost: Optional[Cost] = None

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def to_dict(self) -> dict:
        payload = {
            "index": self.index,
            "purpose": self.purpose,
            "model": self.model,
            "duration_ms": self.duration_ms,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "input": self.input.to_dict(),
            "output": self.output.to_dict(),
        }
        if self.cost is not None:
            payload["cost"] = self.cost.to_dict()
        return payload


@dataclass
class ToolCall:
    """A call the model chose to make. Retrieval by the pipeline is never one."""

    index: int
    name: str
    arguments: dict
    result_chars: int
    duration_ms: int
    status: Status = "ok"

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "name": self.name,
            "arguments": self.arguments,
            "result_chars": self.result_chars,
            "duration_ms": self.duration_ms,
            "status": self.status,
        }


@dataclass
class RunStep:
    index: int
    name: str
    kind: StepKind
    duration_ms: int
    status: Status = "ok"
    # Human-readable outcome: a state transition, a score band, a hold reason,
    # or — for a degraded step — the reason it degraded, naming the offending
    # value when the model was wrong.
    detail: Optional[str] = None

    def to_dict(self) -> dict:
        payload = {
            "index": self.index,
            "name": self.name,
            "kind": self.kind,
            "duration_ms": self.duration_ms,
            "status": self.status,
        }
        if self.detail is not None:
            payload["detail"] = self.detail
        return payload


@dataclass
class AgentRun:
    run_id: str
    opportunity_id: str
    client_message_id: Optional[str]
    trigger: str
    customer_message_count: int
    started_at: datetime
    finished_at: datetime
    duration_ms: int
    steps: list[RunStep] = field(default_factory=list)
    llm_calls: list[LlmCall] = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)

    @property
    def status(self) -> Status:
        statuses = {step.status for step in self.steps}
        if "error" in statuses:
            return "error"
        if "degraded" in statuses:
            return "degraded"
        return "ok"

    @property
    def total_tokens(self) -> int:
        return sum(call.total_tokens for call in self.llm_calls)

    @property
    def total_cost(self) -> Optional[Cost]:
        priced = [call.cost for call in self.llm_calls if call.cost is not None]
        if not priced:
            return None
        return Cost(amount=sum(cost.amount for cost in priced), currency=priced[0].currency)

    @property
    def degraded_reasons(self) -> list[str]:
        return [step.detail for step in self.steps if step.status == "degraded" and step.detail]

    def totals(self) -> dict:
        payload = {
            "agent_step_count": len(self.steps),
            "llm_call_count": len(self.llm_calls),
            "tool_call_count": len(self.tool_calls),
            "total_tokens": self.total_tokens,
        }
        cost = self.total_cost
        if cost is not None:
            payload["cost"] = cost.to_dict()
        return payload

    def to_dict(self, *, include_content: bool) -> dict:
        llm_calls = self.llm_calls
        if not include_content:
            llm_calls = [
                LlmCall(
                    index=call.index,
                    purpose=call.purpose,
                    model=call.model,
                    duration_ms=call.duration_ms,
                    prompt_tokens=call.prompt_tokens,
                    completion_tokens=call.completion_tokens,
                    input=Content(chars=call.input.chars),
                    output=Content(chars=call.output.chars),
                    cost=call.cost,
                )
                for call in self.llm_calls
            ]
        return {
            "run_id": self.run_id,
            "opportunity_id": self.opportunity_id,
            "client_message_id": self.client_message_id,
            "trigger": self.trigger,
            "customer_message_count": self.customer_message_count,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "duration_ms": self.duration_ms,
            "status": self.status,
            "steps": [step.to_dict() for step in self.steps],
            "llm_calls": [call.to_dict() for call in llm_calls],
            "tool_calls": [call.to_dict() for call in self.tool_calls],
            "totals": self.totals(),
        }
