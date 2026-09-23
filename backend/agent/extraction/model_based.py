# -*- coding: utf-8 -*-
"""Model-based extraction: the pydantic-ai peer of `extraction.rules`.

A fresh `pydantic_ai.Agent` is built per call rather than reused across turns:
the tools it registers close over this call's own trimmed history and its
own handoff-proposal slot, so the model is never asked to supply the
transcript as an argument (which would invite it to invent one) and a
proposal from one run can never leak into the next.

Three failure classes, kept distinguishable on the outcome and on the run
record (`docs/backend-plan.md` §7):

    model wrong         an out-of-enum value fails Pydantic validation and
                        surfaces as `UnexpectedModelBehavior` with the
                        `ValidationError` as its cause; recorded as a named
                        contract violation, never silently downgraded
    model unavailable   no endpoint, timeout, rate limit, usage guard tripped;
                        recorded as `unavailable`, rule peer takes the turn
    program error       anything else propagates
"""
from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timezone
from typing import Optional

from pydantic import ValidationError
from pydantic_ai import Agent
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.models import Model
from pydantic_ai.usage import UsageLimits

from ... import config
from ...domain.detection import Detection, HandoffProposal
from ...domain.enums import Intent
from ...domain.message import Message
from ...observability import RunRecorder, StepHandle
from .. import policy, telemetry
from ..schema import ExtractionOutput
from ..tools import (
    compare_products,
    get_conversation_summary,
    list_products,
    lookup_product_fact,
    request_human_handoff,
)
from . import rules

# Intents that gate whether a human must be involved at all (`kernel.hitl`'s
# "outside the assistant's authority" triggers). A model's own semantic read
# has no keyword safety net the way `solicitation` always does below, so a
# near-verbatim "I want to cancel my policy" or "speak to a human" could
# silently fail to escalate purely because this run's model classified it
# differently. A missed escalation is the costly failure direction here, so
# the deterministic read wins whenever it fires — the same "the deterministic
# marker settles it" idea `kernel/qualification.py` already applies to
# solicitation, extended to these three intents.
_ESCALATION_CRITICAL_INTENTS = frozenset({Intent.HUMAN_REQUEST, Intent.COMPLAINT, Intent.UNDERWRITING})


def extract(
    text: str,
    context: Optional[list[Message]] = None,
    *,
    model: Model,
    recorder: Optional[RunRecorder] = None,
):
    from . import ExtractionOutcome  # deferred: avoids a circular import at load time

    trimmed = policy.trim_history(context or [])
    proposal: list[HandoffProposal] = []
    agent = Agent(
        model,
        output_type=ExtractionOutput,
        system_prompt=policy.EXTRACTION_SYSTEM_PROMPT,
        retries=1,
    )
    agent.tool_plain(lookup_product_fact)
    agent.tool_plain(compare_products)
    agent.tool_plain(list_products)
    agent.tool_plain(_bind_summary_tool(trimmed), name="get_conversation_summary")
    agent.tool_plain(_bind_handoff_tool(proposal), name="request_human_handoff")

    # The deterministic read, computed once and reused below: `solicitation`
    # is always taken from here regardless of which branch fires (see
    # `backend/domain/detection.py`), and on a successful model run further
    # down it also corroborates `signals` (unioned in) and the escalation-
    # critical intents above (rule wins when it fires).
    rule_based = rules.extract(text, context)
    solicitation = rule_based.solicitation

    # A null step keeps the happy path free of `if recorder` branches.
    step_cm = recorder.step("extraction", "llm") if recorder else nullcontext(StepHandle())
    with step_cm as step:
        try:
            result = agent.run_sync(text, usage_limits=_usage_limits())
        except UnexpectedModelBehavior as exc:
            violation = _describe_violation(exc)
            step.degrade(violation)
            return ExtractionOutcome(detection=rule_based, source="rule", violation=violation)
        except telemetry.UNAVAILABLE_ERRORS as exc:
            reason = telemetry.describe_unavailable(exc)
            step.degrade(reason)
            return ExtractionOutcome(detection=rule_based, source="rule", unavailable=reason)

        messages = result.all_messages()
        if recorder is not None:
            telemetry.record_trace(
                recorder,
                messages,
                purpose="extraction",
                finished_at=datetime.now(timezone.utc),
            )
        output = result.output
        step.note(f"intent={output.intent.value} product={output.product.value}")

    merged_signals = list(output.signals)
    for signal in rule_based.signals:
        if signal not in merged_signals:
            merged_signals.append(signal)

    intent = output.intent
    if rule_based.intent in _ESCALATION_CRITICAL_INTENTS:
        intent = rule_based.intent

    detection = Detection(
        intent=intent,
        product=output.product,
        signals=merged_signals,
        concerns=list(output.concerns),
        restricted=output.restricted,
        cancellation=output.cancellation,
        postponement=output.postponement,
        genuine_enquiry=output.genuine_enquiry,
        solicitation=solicitation,
    )
    return ExtractionOutcome(
        detection=detection,
        source="llm",
        handoff=proposal[0] if proposal else None,
        trace=list(messages),
    )


def _usage_limits() -> UsageLimits:
    # `docs/backend-plan.md` §12.3: a runaway tool loop is quadratic in the
    # number of tool calls, so it is capped before it can cost anything.
    steps = config.LLM_MAX_TOOL_STEPS
    return UsageLimits(request_limit=steps + 2, tool_calls_limit=steps)


def _bind_summary_tool(history: list[Message]):
    def get_conversation_summary_tool() -> str:
        """Recap of the conversation so far, most recent messages only."""
        return get_conversation_summary(history)

    return get_conversation_summary_tool


def _bind_handoff_tool(slot: list[HandoffProposal]):
    def request_human_handoff_tool(reason: str) -> str:
        """Propose that a person take over this conversation, and say why.

        This is a proposal only; whether a handover actually happens is
        decided elsewhere.
        """
        slot.clear()
        slot.append(request_human_handoff(reason))
        return "Handover proposed. Continue with your observations."

    return request_human_handoff_tool


def _describe_violation(exc: UnexpectedModelBehavior) -> str:
    cause = exc.__cause__
    if isinstance(cause, ValidationError) and cause.errors():
        error = cause.errors()[0]
        field = ".".join(str(part) for part in error["loc"])
        value = error.get("input")
        return f"model returned {field}={value!r}, not a member of the domain enum → fell back to rules"
    return f"model output failed contract validation → fell back to rules ({exc})"
