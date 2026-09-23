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

`customer_message` is the customer's own raw text for this turn, included
verbatim in the prompt so the model can see exactly how the question was
phrased. An earlier version continued the *extraction* agent's own
conversation here instead (`ExtractionOutcome.trace`, via pydantic-ai's
`message_history`) — but that agent's trace is full of tool-call/tool-result
content blocks, and this agent registers no tools of its own, which at least
one OpenAI-compatible gateway (Bedrock-backed) rejects outright: "toolConfig
field must be defined when using toolUse and toolResult content blocks." The
only information that history was actually carrying for this agent's purposes
was the customer's own words, so that is now passed directly instead.
"""
from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timezone
from typing import Optional

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
    greeting: bool = False,
    customer_message: Optional[str] = None,
) -> Message:
    developer_prompt = _build_user_prompt(instruction, retrieval)
    # Checked before the customer's own words are appended: this is the
    # generous, developer/KB-vocabulary check (`policy.assert_customer_safe`),
    # and a customer is free to type any of those ordinary words themselves
    # without that being a leak of anything.
    policy.assert_customer_safe(developer_prompt)
    prompt = developer_prompt
    if customer_message:
        prompt += f"\n\nThe customer's message: {customer_message}"

    agent = Agent(model, system_prompt=policy.REPLY_SYSTEM_PROMPT, retries=1)

    step_cm = recorder.step(STEP_NAME, "llm") if recorder else nullcontext(StepHandle())
    with step_cm as step:
        try:
            result = agent.run_sync(prompt)
        except telemetry.UNAVAILABLE_ERRORS as exc:
            step.degrade(telemetry.describe_unavailable(exc))
            return template.compose(retrieval=retrieval, greeting=greeting, recorder=recorder)
        if recorder is not None:
            telemetry.record_trace(
                recorder,
                result.new_messages(),
                purpose=STEP_NAME,
                finished_at=datetime.now(timezone.utc),
            )
        try:
            policy.assert_reply_safe(result.output)
        except ValueError as exc:
            # A genuine leak must never reach the customer, but it also must
            # not crash the turn — degrade to the safe template peer instead,
            # the same outcome as an unavailable model.
            step.degrade(str(exc))
            return template.compose(retrieval=retrieval, greeting=greeting, recorder=recorder)
        step.note(f"chars={len(result.output)}")

    output = result.output
    if retrieval.mentions_premium and config.DEMO_DISCLAIMER not in output:
        # The prompt already asks the model to append this verbatim, but that
        # is an instruction, not a guarantee: a compliance red line
        # (`.kiro/steering/product.md` — never hidden or truncated) cannot
        # depend on a model reliably reproducing exact text across every
        # generation. Enforced here the same way the template peer always
        # has, so the property holds regardless of which peer answered.
        output = f"{output}\n\n{config.DEMO_DISCLAIMER}"

    return Message.from_ai(output, generation=Generation.LLM)


def _build_user_prompt(instruction: str, retrieval: RetrievalResult) -> str:
    lines = [instruction, "", "Approved facts:"]
    lines.extend(f"- {fact}" for fact in retrieval.facts[:4])
    if retrieval.mentions_premium:
        lines.append(f"Disclaimer to append verbatim if a premium is shown: {config.DEMO_DISCLAIMER}")
    return "\n".join(lines)
