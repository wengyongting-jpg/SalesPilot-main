# -*- coding: utf-8 -*-
"""Model-based extraction: the pydantic-ai peer of `extraction.rules`.

A `ToolContext` is built fresh per call and bound to each tool function via
`functools.partial` before registration, so the model is never offered `context`
as an argument it must supply (and never asked to invent a transcript) and a
proposal or violation from one run can never leak into the next.

Three failure classes, kept distinguishable on the outcome and on the run
record (`docs/backend-plan.md` §7):

    model wrong         an out-of-enum value fails Pydantic validation and
                        surfaces as `UnexpectedModelBehavior` with the
                        `ValidationError` as its cause; recorded as a named
                        `ModelViolation`, never silently downgraded
    model unavailable   no endpoint, timeout, rate limit, usage guard tripped;
                        recorded as `unavailable`, rule peer takes the turn
    program error       anything else propagates
"""
from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timezone
from functools import partial
from typing import Optional

from pydantic import ValidationError
from pydantic_ai import Agent
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.models import Model
from pydantic_ai.usage import UsageLimits

from ... import config
from ...domain.detection import Detection
from ...domain.enums import Intent
from ...domain.message import Message
from ...knowledge import loader
from ...observability import RunRecorder, StepHandle
from ...observability.violations import ModelViolation
from .. import policy, schema, telemetry
from ..schema import ExtractionOutput
from ..tools import (
    ToolContext,
    compare_products,
    conversation_summary,
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

    tool_context = ToolContext(kb=loader.load())
    agent = Agent(
        model,
        output_type=ExtractionOutput,
        system_prompt=policy.extraction_system_prompt(),
        retries=1,
    )
    agent.tool_plain(_bind(lookup_product_fact, tool_context), name="lookup_product_fact")
    agent.tool_plain(_bind(compare_products, tool_context), name="compare_products")
    agent.tool_plain(_bind(list_products, tool_context), name="list_products")
    agent.tool_plain(_bind(conversation_summary, tool_context), name="get_conversation_summary")
    agent.tool_plain(_bind(request_human_handoff, tool_context), name="request_human_handoff")

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
            violation = _model_violation(exc)
            step.degrade(violation.describe())
            return ExtractionOutcome(detection=rule_based, source="rules", violations=[violation])
        except telemetry.UNAVAILABLE_ERRORS as exc:
            reason = telemetry.describe_unavailable(exc)
            step.degrade(reason)
            return ExtractionOutcome(detection=rule_based, source="rules", unavailable=reason)

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
    handoff = tool_context.handoff if tool_context.handoff.requested else None
    return ExtractionOutcome(
        detection=detection,
        source="llm",
        violations=list(tool_context.violations),
        handoff=handoff,
        trace=list(messages),
    )


def _bind(fn, tool_context: ToolContext):
    """Bind `tool_context` as `fn`'s first argument for tool registration.

    `functools.partial` (unlike a plain closure) is what makes
    `inspect.signature()` correctly drop the bound first parameter, so
    pydantic-ai builds the model-facing schema from the *remaining*
    arguments only — the model is never offered `context` as something it
    must supply. `partial` objects have no `__name__`/`__doc__` of their
    own, which pydantic-ai needs for the tool's registry key and
    description, so both are copied across explicitly.
    """
    bound = partial(fn, tool_context)
    bound.__name__ = fn.__name__
    bound.__qualname__ = fn.__qualname__
    bound.__doc__ = fn.__doc__
    return bound


def _model_violation(exc: UnexpectedModelBehavior) -> ModelViolation:
    cause = exc.__cause__
    if isinstance(cause, ValidationError) and cause.errors():
        error = cause.errors()[0]
        field_name = str(error["loc"][0]) if error["loc"] else "output"
        value = error.get("input")
        allowed = schema.allowed_values().get(field_name, [])
        return ModelViolation(field=field_name, value=str(value), allowed=allowed)
    return ModelViolation(field="output", value=str(exc), allowed=[])


def _usage_limits() -> UsageLimits:
    # `docs/backend-plan.md` §12.3: a runaway tool loop is quadratic in the
    # number of tool calls, so it is capped before it can cost anything.
    steps = config.LLM_MAX_TOOL_STEPS
    return UsageLimits(request_limit=steps + 2, tool_calls_limit=steps)
