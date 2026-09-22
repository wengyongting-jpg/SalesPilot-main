# -*- coding: utf-8 -*-
"""Building an `AgentRun` as the pipeline executes.

One `RunRecorder` per processed message. Each layer records its own steps
through the same small API — the extraction and reply peers in `agent/`, the
kernel steps in `services/` — so the record is complete without any layer
knowing about the others.

An exception inside a step marks it `error` and re-raises. A program error
stays a program error (`docs/backend-plan.md` §7's first failure class);
only the caller can decide a step *degraded*, by saying so.
"""
from __future__ import annotations

import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Iterator, Optional

from .. import config
from . import pricing
from .run import AgentRun, Content, LlmCall, RunStep, StepKind, Status, ToolCall


@dataclass
class StepHandle:
    """What a step may say about itself while it runs."""

    status: Status = "ok"
    detail: Optional[str] = None

    def degrade(self, reason: str) -> None:
        self.status = "degraded"
        self.detail = reason

    def note(self, detail: str) -> None:
        self.detail = detail


class RunRecorder:
    def __init__(
        self,
        opportunity_id: str,
        *,
        client_message_id: Optional[str] = None,
        trigger: str = "customer_message",
        customer_message_count: int = 0,
        content_enabled: Optional[bool] = None,
        content_max_chars: Optional[int] = None,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self.run_id = f"ar-{uuid.uuid4().hex[:4]}"
        self.opportunity_id = opportunity_id
        self.client_message_id = client_message_id
        self.trigger = trigger
        self.customer_message_count = customer_message_count
        self._content_enabled = (
            config.TELEMETRY_CONTENT if content_enabled is None else content_enabled
        )
        self._content_max_chars = (
            config.TELEMETRY_CONTENT_MAX_CHARS if content_max_chars is None else content_max_chars
        )
        self._clock = clock
        self._started_at = datetime.now(timezone.utc)
        self._t0 = clock()
        self.steps: list[RunStep] = []
        self.llm_calls: list[LlmCall] = []
        self.tool_calls: list[ToolCall] = []

    # ---- Steps --------------------------------------------------------------

    @contextmanager
    def step(self, name: str, kind: StepKind) -> Iterator[StepHandle]:
        # The slot is reserved on entry so a step keeps its place ahead of any
        # tool calls recorded while it runs — the order a reader expects.
        record = RunStep(index=len(self.steps), name=name, kind=kind, duration_ms=0)
        self.steps.append(record)
        handle = StepHandle()
        start = self._clock()
        try:
            yield handle
        except BaseException:
            record.duration_ms = self._elapsed_ms(start)
            record.status = "error"
            raise
        record.duration_ms = self._elapsed_ms(start)
        record.status = handle.status
        record.detail = handle.detail

    # ---- Model and tool calls ----------------------------------------------

    def llm_call(
        self,
        *,
        purpose: str,
        model: str,
        duration_ms: int,
        prompt_tokens: int,
        completion_tokens: int,
        input_text: str,
        output_text: str,
    ) -> LlmCall:
        call = LlmCall(
            index=len(self.llm_calls),
            purpose=purpose,
            model=model,
            duration_ms=duration_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            input=self._content(input_text),
            output=self._content(output_text),
            cost=pricing.cost_for(model, prompt_tokens, completion_tokens),
        )
        self.llm_calls.append(call)
        return call

    def tool_call(
        self,
        *,
        name: str,
        arguments: dict,
        result_chars: int,
        duration_ms: int,
        status: Status = "ok",
    ) -> ToolCall:
        """A model-selected call. Also appears as a `kind="tool"` step (§7)."""
        call = ToolCall(
            index=len(self.tool_calls),
            name=name,
            arguments=arguments,
            result_chars=result_chars,
            duration_ms=duration_ms,
            status=status,
        )
        self.tool_calls.append(call)
        self.steps.append(
            RunStep(
                index=len(self.steps),
                name=f"tool.{name}",
                kind="tool",
                duration_ms=duration_ms,
                status=status,
                detail=" ".join(f"{key}={value}" for key, value in arguments.items()) or None,
            )
        )
        return call

    # ---- Finish -----------------------------------------------------------------

    def finish(self) -> AgentRun:
        return AgentRun(
            run_id=self.run_id,
            opportunity_id=self.opportunity_id,
            client_message_id=self.client_message_id,
            trigger=self.trigger,
            customer_message_count=self.customer_message_count,
            started_at=self._started_at,
            finished_at=datetime.now(timezone.utc),
            duration_ms=self._elapsed_ms(self._t0),
            steps=list(self.steps),
            llm_calls=list(self.llm_calls),
            tool_calls=list(self.tool_calls),
        )

    # ---- Internals ----------------------------------------------------------

    def _elapsed_ms(self, start: float) -> int:
        return int(round((self._clock() - start) * 1000))

    def _content(self, text: str) -> Content:
        chars = len(text)
        if not self._content_enabled:
            return Content(chars=chars)
        return Content(chars=chars, content=text[: self._content_max_chars])
