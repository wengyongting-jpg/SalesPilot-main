# -*- coding: utf-8 -*-
"""Agent run records, cost accounting and terminal rendering.

Answers a question the original build could not: what did the agent actually do,
and did any step go wrong without raising?

Three failure classes must stay distinguishable, because conflating them is what
made debugging impossible before:

    program error       an exception; surfaced as 5xx and a stack trace
    model unavailable   no key, timeout, rate limit; step status "degraded"
    model wrong         invalid enum, unparsable output, ignored instruction;
                        step status "degraded" plus a violation naming the value

Never imported by `domain` or `kernel`.
"""
from .console import print_run, render
from .recorder import RunRecorder, StepHandle
from .run import AgentRun, Cost, LlmCall, RunStep, ToolCall

__all__ = [
    "AgentRun",
    "Cost",
    "LlmCall",
    "RunRecorder",
    "RunStep",
    "StepHandle",
    "ToolCall",
    "print_run",
    "render",
]
