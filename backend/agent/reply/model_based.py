# -*- coding: utf-8 -*-
"""Model-based reply composition: the pydantic-ai peer of `reply.template`.

Receives only a customer-safe instruction (`policy.customer_safe_projection`)
and approved knowledge facts — never a raw state, score, signal list, or
`NextBestAction` object, none of which `agent` can even import. The assembled
prompt is checked with `policy.assert_customer_safe` before it is sent and
the model's own output is checked again after, so this is enforced at run
time, not only in tests. A breach there is a program error, not a
degradation: it propagates.

When the model is unavailable the template peer takes the turn and the run
record says so (`generation="template"`, step `degraded`) — the offline
outcome `interface-v1.md` §5.7 describes, never a silent substitution.

`message_history` continues the conversation the extraction step ran
(`docs/backend-plan.md` §3's "one continuous conversation"): pass
`ExtractionOutcome.trace`. Optional, so this module is independently callable.
"""
from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic_ai import Agent
from pydantic_ai.models import Model

from ... import config
from ...domain.detection import RetrievalResult
from ...domain.enums import Generation
from ...domain.message import Message
from ...observability import RunRecorder, StepHandle
from .. import policy, telemetry
from . import template

STEP_NAME = "response_generation"


def compose(
    instruction: str,
    retrieval: RetrievalResult,
    *,
    model: Model,
    recorder: Optional[RunRecorder] = None,
    message_history: Optional[list[Any]] = None,
) -> Message:
    prompt = _build_user_prompt(instruction, retrieval)
    policy.assert_customer_safe(prompt)

    agent = Agent(model, system_prompt=policy.REPLY_SYSTEM_PROMPT, retries=1)

    step_cm = recorder.step(STEP_NAME, "llm") if recorder else nullcontext(StepHandle())
    with step_cm as step:
        try:
            result = agent.run_sync(prompt, message_history=message_history)
        except telemetry.UNAVAILABLE_ERRORS as exc:
            step.degrade(telemetry.describe_unavailable(exc))
            return template.compose(retrieval=retrieval, recorder=recorder)
        if recorder is not None:
            telemetry.record_trace(
                recorder,
                result.new_messages(),
                purpose=STEP_NAME,
                finished_at=datetime.now(timezone.utc),
            )
        step.note(f"chars={len(result.output)}")

    policy.assert_customer_safe(result.output)
    return Message.from_ai(result.output, generation=Generation.LLM)


def _build_user_prompt(instruction: str, retrieval: RetrievalResult) -> str:
    lines = [instruction, "", "Approved facts:"]
    lines.extend(f"- {fact}" for fact in retrieval.facts[:4])
    if any("premium" in fact.lower() for fact in retrieval.facts):
        lines.append(f"Disclaimer to append verbatim if a premium is shown: {config.DEMO_DISCLAIMER}")
    return "\n".join(lines)
