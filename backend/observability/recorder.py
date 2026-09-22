# -*- coding: utf-8 -*-
"""Recording one agent run, step by step.

Used by `services` to wrap the pipeline. The kernel is never instrumented — business
rules stay readable and unit-testable with no recorder in scope, which is why
`kernel` has no permission to import this package.

Two design choices worth the words.

**The clock is injected.** Durations otherwise depend on wall time, which makes the
record unreproducible and the tests flaky. Same reasoning as the injected `now` in
`kernel.scoring`: a measurement you cannot reproduce is hard to trust.

**A step records its failure before re-raising.** An exception still propagates —
this is not a swallow — but the run keeps the evidence of where it happened. The
previous build's failures left nothing behind, so a debugging session began by
guessing.
"""
from __future__ import annotations

import time
import traceback
from contextlib import contextmanager
from datetime import datetime
from typing import Callable, Iterable, Optional

from .pricing import cost_for
from .run import AgentRun, Content, LlmCall, RunStatus, RunStep, StepKind, ToolCallRecord
from .violations import ModelViolation

DEFAULT_CONTENT_MAX_CHARS = 8000


class StepHandle:
    """Passed to the body of a `step()` block so it can report what happened.

    A step that simply returns is `ok`. Anything else has to be said out loud.
    """

    def __init__(self, step: RunStep, recorder: "RunRecorder") -> None:
        self._step = step
        self._recorder = recorder

    def degraded(self, reason: str, *, by_design: bool = False) -> None:
        """The step produced a usable result by a worse route.

        `by_design` marks a degradation that is the configured mode rather than a
        fault — the offline peers running because no model is configured. It changes
        the log level and nothing else; the step still reports `degraded` on the wire,
        because from a reader's point of view it genuinely did take the worse route.

        Defaults to False so a new degradation has to claim to be expected rather than
        being treated as expected by omission.

        A step can degrade more than once. Expected stays expected only if **every**
        reason was expected, so one real fault alongside an offline fallback still
        earns a warning.
        """
        first = self._step.status is not RunStatus.DEGRADED
        self._step.status = RunStatus.DEGRADED
        self._step.by_design = by_design if first else (
            self._step.by_design and by_design
        )
        self._append_detail(reason)

    def violation(self, violation: ModelViolation) -> None:
        """The model returned a value the domain rejects.

        Both recorded on the step, so the timeline shows *where* it happened, and
        collected on the run, so a reader does not have to hunt for it.
        """
        self._recorder.run.violations.append(violation)
        self._step.status = RunStatus.DEGRADED
        # Never expected. The model and the domain have disagreed, which is the defect
        # class the rebuild exists to surface, so it must not inherit an offline
        # step's exemption from being warned about.
        self._step.by_design = False
        self._append_detail(violation.describe())

    def note(self, detail: str) -> None:
        """Add context without changing the status."""
        self._append_detail(detail)

    def _append_detail(self, text: str) -> None:
        self._step.detail = f"{self._step.detail}; {text}" if self._step.detail else text


class RunRecorder:
    def __init__(
        self,
        *,
        opportunity_id: str,
        client_message_id: Optional[str] = None,
        trigger: str = "customer_message",
        customer_message_count: int = 0,
        capture_content: bool = True,
        content_max_chars: int = DEFAULT_CONTENT_MAX_CHARS,
        clock: Callable[[], float] = time.perf_counter,
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.clock = clock
        self.now = now
        self.capture_content = capture_content
        self.content_max_chars = content_max_chars
        self._started = clock()
        self.run = AgentRun(
            opportunity_id=opportunity_id,
            client_message_id=client_message_id,
            trigger=trigger,
            customer_message_count=customer_message_count,
            started_at=now(),
        )

    # ---- Steps -----------------------------------------------------------

    @contextmanager
    def step(self, name: str, kind: StepKind):
        record = RunStep(
            index=len(self.run.steps), name=name, kind=kind, duration_ms=0
        )
        self.run.steps.append(record)
        handle = StepHandle(record, self)
        began = self.clock()
        try:
            yield handle
        except Exception as error:
            record.status = RunStatus.ERROR
            handle.note(
                f"{type(error).__name__}: {error}\n"
                + "".join(traceback.format_exc(limit=6)).rstrip()
            )
            raise
        finally:
            record.duration_ms = self._elapsed_ms(began)

    # ---- Model calls -----------------------------------------------------

    def record_llm_call(
        self,
        *,
        purpose: str,
        model: str,
        duration_ms: int,
        prompt_tokens: int,
        completion_tokens: int,
        input_text: str = "",
        output_text: str = "",
    ) -> LlmCall:
        call = LlmCall(
            index=len(self.run.llm_calls),
            purpose=purpose,
            model=model,
            duration_ms=duration_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost=cost_for(model, prompt_tokens, completion_tokens),
            input=self._content(input_text),
            output=self._content(output_text),
        )
        self.run.llm_calls.append(call)
        return call

    def record_tool_calls(self, tool_calls: Iterable) -> None:
        """Record the calls the **model chose** to make.

        Takes `agent.tools.ToolCall` objects. Only model-selected calls reach here;
        pipeline retrieval is a step with `kind=retrieval` and is not a tool call.
        """
        for call in tool_calls:
            self.run.tool_calls.append(
                ToolCallRecord(
                    index=len(self.run.tool_calls),
                    name=call.name,
                    arguments=dict(call.arguments),
                    result_chars=call.result_chars,
                )
            )

    def record_violations(self, violations: Iterable[ModelViolation]) -> None:
        for violation in violations:
            self.run.violations.append(violation)

    # ---- Completion ------------------------------------------------------

    def finish(self) -> AgentRun:
        self.run.finished_at = self.now()
        self.run.duration_ms = self._elapsed_ms(self._started)
        self.run.status = self._overall_status()
        return self.run

    def _overall_status(self) -> RunStatus:
        """The worst thing that happened.

        An error outranks a degradation: the two send a reader to different places, so
        the summary must name the more serious one.
        """
        worst = RunStatus.OK
        for step in self.run.steps:
            if step.status.severity > worst.severity:
                worst = step.status
        if worst is RunStatus.OK and self.run.violations:
            return RunStatus.DEGRADED
        return worst

    # ---- Internals -------------------------------------------------------

    def _elapsed_ms(self, began: float) -> int:
        return int(round((self.clock() - began) * 1000))

    def _content(self, text: str) -> Content:
        text = text or ""
        if not self.capture_content:
            # The length is still reported: a frontend must be able to render
            # "2,180 characters withheld" rather than showing nothing.
            return Content(chars=len(text), content=None)
        if len(text) <= self.content_max_chars:
            return Content(chars=len(text), content=text)
        # ASCII elision: this content is rendered in terminals and logs as well as
        # served over HTTP.
        return Content(
            chars=len(text),
            content=text[: self.content_max_chars - 3] + "...",
        )
