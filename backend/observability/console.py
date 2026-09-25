# -*- coding: utf-8 -*-
"""Terminal rendering of one agent run — `docs/v0.0/backend/backend-plan.md` §7.

    ▶ run ar-91c4  C-1024  customer_message  key=c-8f2a1b40
      0 extraction           llm        820ms  ok      gpt-4o-mini  412+88=500 tok  $0.00021
      1 tool.lookup_fact     tool        12ms  ok      product=plus field=premium
      2 state_transition     rule         1ms  ok      Potential Interest -> Evaluation & Hesitation
      ✔ ok  1240ms  2 llm  1 tool  862 tok  $0.00036

Degradations and contract violations print as warnings, not as silence.
`render` is pure so tests can assert on it; `print_run` is the gated side
effect.
"""
from __future__ import annotations

import sys
import textwrap

from .. import config
from .run import AgentRun, LlmCall, RunStep

_NAME_WIDTH = 24
_KIND_WIDTH = 10
_STATUS_WIDTH = 8
_WRAP_WIDTH = 80

_MARK_RUN = ">"
_MARK_OK = "[OK]"
_MARK_DEGRADED = "[WARN]"
_MARK_ERROR = "[ERROR]"

_RESET = "\033[0m"
_COLOURS = {"ok": "\033[32m", "degraded": "\033[33m", "error": "\033[31m"}


def render(run: AgentRun, *, colour: bool = False) -> str:
    lines = [_header(run)]
    for step in run.steps:
        calls = [c for c in run.llm_calls if c.purpose == step.name] if step.kind == "llm" else []
        lines.extend(_step_lines(step, calls, colour))
    lines.append(_footer(run, colour))
    return "\n".join(lines)


def print_run(run: AgentRun) -> None:
    if not config.CONSOLE_TRACE:
        return
    colour = config.CONSOLE_COLOUR and sys.stdout.isatty()
    print(render(run, colour=colour))


# ---- Pieces --------------------------------------------------------------------


def _header(run: AgentRun) -> str:
    head = f"{_MARK_RUN} run {run.run_id}  {run.opportunity_id}  {run.trigger}"
    if run.client_message_id:
        head += f"  key={run.client_message_id}"
    return head


def _step_lines(step: RunStep, calls: list[LlmCall], colour: bool) -> list[str]:
    status_text = step.status if step.status == "ok" else step.status.upper()
    painted = _paint(status_text, step.status, colour)
    prefix = (
        f"  {step.index} {step.name:<{_NAME_WIDTH}} {step.kind:<{_KIND_WIDTH}}"
        f"{step.duration_ms:>6}ms  {painted:<{_STATUS_WIDTH}}"
    )
    detail = _detail(step, calls)
    if not detail:
        return [prefix.rstrip()]
    if step.status == "ok":
        return [f"{prefix}  {detail}"]
    # A degraded/error reason may be long; wrap it under the status column so
    # the offending value is never cut off.
    wrapped = textwrap.wrap(detail, width=_WRAP_WIDTH)
    indent = " " * (len(prefix) + 2)
    first, rest = wrapped[0], wrapped[1:]
    return [f"{prefix}  {first}"] + [f"{indent}{line}" for line in rest]


def _detail(step: RunStep, calls: list[LlmCall]) -> str:
    if step.status != "ok":
        return step.detail or ""
    if step.kind == "llm" and calls:
        prompt = sum(c.prompt_tokens for c in calls)
        completion = sum(c.completion_tokens for c in calls)
        priced = [c.cost.amount for c in calls if c.cost is not None]
        cost = f"  ${sum(priced):.5f}" if priced else ""
        requests = f"  {len(calls)} req" if len(calls) > 1 else ""
        return f"{calls[0].model}  {prompt}+{completion}={prompt + completion} tok{cost}{requests}"
    return step.detail or ""


def _footer(run: AgentRun, colour: bool) -> str:
    status = run.status
    if status == "ok":
        cost = f"  ${run.total_cost.amount:.5f}" if run.total_cost is not None else ""
        return (
            f"  {_paint(_MARK_OK, 'ok', colour)}  {run.duration_ms}ms  "
            f"{len(run.llm_calls)} llm  {len(run.tool_calls)} tool  "
            f"{run.total_tokens} tok{cost}"
        )
    if status == "degraded":
        reason = run.degraded_reasons[0] if run.degraded_reasons else "a step degraded"
        return f"  {_paint(_MARK_DEGRADED, 'degraded', colour)}  {reason}"
    failed = next((s.name for s in run.steps if s.status == "error"), "unknown step")
    return f"  {_paint(_MARK_ERROR, 'error', colour)}  {failed} raised"


def _paint(text: str, status: str, colour: bool) -> str:
    if not colour:
        return text
    return f"{_COLOURS.get(status, '')}{text}{_RESET}"
