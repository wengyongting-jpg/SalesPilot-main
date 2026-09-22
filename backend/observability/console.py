# -*- coding: utf-8 -*-
"""Rendering an agent run for a terminal.

One block per run: a header, a line per step, and a totals line. The point is that
somebody watching the server can see what the agent did and, crucially, **that
something went wrong without an exception being raised**.

ASCII by default, deliberately. A Windows console at its default code page mangles
box-drawing glyphs and arrows, and a report about something being broken should not
itself look broken. Unicode markers are available for a terminal known to handle them.
"""
from __future__ import annotations

from dataclasses import dataclass

from .run import AgentRun, RunStatus


@dataclass(frozen=True)
class Glyphs:
    header: str
    ok: str
    degraded: str
    error: str


ASCII = Glyphs(header=">", ok="[ok]", degraded="[!]", error="[X]")
UNICODE = Glyphs(header="\u25b6", ok="\u2714", degraded="\u26a0", error="\u2716")

_STATUS_LABEL = {
    RunStatus.OK: "ok",
    RunStatus.DEGRADED: "DEGRADED",
    RunStatus.ERROR: "ERROR",
}

_INDENT = "  "


def render(run: AgentRun, *, glyphs: Glyphs = ASCII, width: int = 96) -> str:
    """The whole block, as one string. Returned rather than printed so it can be
    logged, tested and captured as easily as displayed.

    Only the column-aligned lines are clipped to `width`. Detail lines — a
    degradation reason, a violation with its permitted values, a stack trace — are
    never clipped: they are the diagnostic payload, and the first version of this
    renderer cut them off mid-sentence at exactly the words a reader needed.
    """
    lines = [(_header(run, glyphs), True)]
    lines.extend(_step_lines(run))
    lines.append((_footer(run, glyphs), True))
    return "\n".join(
        _clip(line, width) if clippable else line for line, clippable in lines
    )


def _header(run: AgentRun, glyphs: Glyphs) -> str:
    parts = [f"{glyphs.header} run {run.run_id}", run.opportunity_id, run.trigger]
    if run.client_message_id:
        parts.append(f"key={run.client_message_id}")
    return "  ".join(parts)


def _step_lines(run: AgentRun) -> list[tuple[str, bool]]:
    # Model calls are matched to steps by purpose, so the model, tokens and cost
    # appear on the line of the step that incurred them rather than in a separate
    # table the reader has to join by eye.
    by_purpose: dict[str, list] = {}
    for call in run.llm_calls:
        by_purpose.setdefault(call.purpose, []).append(call)

    lines = []
    for step in run.steps:
        fields = [
            f"{_INDENT}{step.index}",
            f"{step.name:<22}",
            f"{step.kind.value:<10}",
            f"{step.duration_ms:>5}ms",
            f"{_STATUS_LABEL[step.status]:<9}",
        ]
        calls = by_purpose.get(step.name, [])
        if calls:
            call = calls.pop(0)
            fields.append(
                f"{call.model}  {call.prompt_tokens}+{call.completion_tokens}"
                f"={call.total_tokens} tok  {call.cost.describe()}"
            )
        lines.append((" ".join(fields).rstrip(), True))
        if step.detail:
            # The first line of the detail sits under the step; a stack trace's
            # remaining lines are indented so the block stays scannable. None are
            # clipped.
            for index, detail_line in enumerate(step.detail.splitlines()):
                prefix = f"{_INDENT}{_INDENT}" if index == 0 else f"{_INDENT}{_INDENT}  "
                lines.append((f"{prefix}{detail_line}", False))
    return lines


def _footer(run: AgentRun, glyphs: Glyphs) -> str:
    marker = {
        RunStatus.OK: glyphs.ok,
        RunStatus.DEGRADED: glyphs.degraded,
        RunStatus.ERROR: glyphs.error,
    }[run.status]
    totals = run.totals()
    parts = [
        f"{_INDENT}{marker} {_STATUS_LABEL[run.status]}",
        f"{run.duration_ms}ms",
        f"{totals['llm_call_count']} llm",
        f"{totals['tool_call_count']} tool",
        f"{totals['total_tokens']} tok",
        run.total_cost.describe(),
    ]
    if run.violations:
        parts.append(f"{len(run.violations)} model contract violation(s)")
    return "  ".join(parts)


def _clip(line: str, width: int) -> str:
    if width <= 0 or len(line) <= width:
        return line
    return line[: width - 1] + "-"
