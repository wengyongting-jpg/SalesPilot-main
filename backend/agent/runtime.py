# -*- coding: utf-8 -*-
"""The agent loop: two segments of one conversation, with the kernel between them.

    observe()   the model leads. It may call read-only tools, more than once, and
                reason again on what came back. Produces typed observations.

    <the caller runs the kernel here — mandatory, exactly once, in `services`>

    compose()   the model leads again, continuing the SAME message history, now with
                a customer-safe projection of the kernel's verdict added as one turn.

"Two segments" is not "two disconnected chats": `compose` is handed the observing
segment's history, so the model that words the reply remembers how it reached its
understanding and what it looked up. `docs/backend-plan.md` §3 has the verified trace.

Why the kernel is not called from here: it must run exactly once whatever the model
does, and in offline mode there is no loop for it to live inside. Keeping it in
`services` makes "exactly once" a property of a line of Python rather than of a
framework's configuration, and keeps the offline and model-backed paths structurally
identical. `agent` has no permission to import `kernel`.

Both paths run with no network. With `model=None` the rule-based and template peers do
the work; with `TestModel` the whole loop including tool selection runs offline.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Optional

# Imported at module level, not inside the factory: the framework resolves a tool's
# annotations against this module's globals when it builds the JSON schema, so a
# function-local import leaves `RunContext` unresolvable. This is also the one package
# permitted to import the framework at all — `test_architecture.py` enforces that.
from pydantic_ai import Agent, RunContext
from pydantic_ai.usage import UsageLimits

from .. import config
from ..domain.decision import NextBestAction
from ..domain.enums import Generation, KnowledgeField, Product
from ..knowledge.loader import KnowledgeBase
from ..observability.violations import ModelViolation
from . import policy, schema
from .extraction import ExtractionOutcome
from .extraction.rules import RuleExtractor
from .reply import ReplyOutcome, ReplyRequest
from .reply.model_based import ModelComposer
from .reply.template import TemplateComposer
from .tools import ToolContext
from .tools import handoff as handoff_tools
from .tools import knowledge as knowledge_tools
from .tools import opportunity as opportunity_tools
from .usage import ModelUsage, from_result

# How many recent messages are re-sent as context. A **bounded** window is what keeps
# cost linear in conversation length rather than quadratic; see
# `docs/backend-plan.md` §12.3, where the unbounded version is *cheaper* at ten turns
# and six times the price by three hundred. Treated as an invariant, not a constant to
# tune casually: `backend/tests/test_agent_runtime.py` asserts the bound.
CONTEXT_WINDOW = 6

# A runaway tool loop costs O(k squared): at fifty calls one message runs to 256,000
# input tokens. Capped, and checked before a request is sent so a breach costs nothing.
MAX_TOOL_CALLS = config.LLM_MAX_TOOL_STEPS


def continuity_history(history: list) -> list:
    """The observing segment's history, trimmed to what the composing segment may see.

    Kept: the customer's own turn. Approved facts are supplied afresh in the reply
    prompt, so the composing model still receives what was looked up without carrying
    protocol-specific tool blocks across two separately configured agents.

    Dropped, and each for a reason:

        the extraction system prompt   it necessarily lists the whole signal and
                                       intent vocabulary, since the extractor has to
                                       be told what it may report. Leaving it in
                                       context while the model writes to a customer
                                       puts that taxonomy one echo away from them.

        tool calls and results          Bedrock rejects tool-use history unless the
                                       second request declares the same tools. The
                                       composing agent intentionally has no tools;
                                       approved facts cross in its data block instead.

        the structured output          the labels the model assigned — "Hesitation",
                                       "Competitive". These are internal assessments
                                       *of* the customer, and `product.md` is explicit
                                       that a customer never sees them.

    This is the correction to a first version that shared the history verbatim. The
    continuity requirement and the visibility tier are both satisfiable; sharing
    everything satisfied only the first.
    """
    from pydantic_ai.messages import (
        ModelResponse,
        SystemPromptPart,
        TextPart,
        ToolCallPart,
        ToolReturnPart,
    )

    kept = []
    for message in history:
        parts = [
            part for part in message.parts
            if not isinstance(
                part, (SystemPromptPart, TextPart, ToolCallPart, ToolReturnPart)
            )
        ]
        if not parts:
            continue
        kept.append(
            ModelResponse(parts=parts)
            if isinstance(message, ModelResponse)
            else type(message)(parts=parts)
        )
    return kept


def build_context(messages: list) -> list:
    """The most recent turns, never more than the window.

    A function rather than an inline slice so the bound has one definition and can be
    asserted directly.
    """
    if not messages:
        return []
    return list(messages[-CONTEXT_WINDOW:])


@dataclass
class Observation:
    """The observing segment's result, and the handle the composing segment needs."""

    extraction: ExtractionOutcome
    tool_context: ToolContext
    history: list[Any] = field(default_factory=list)
    # What the observing call consumed, for `services` to record. None on the offline
    # path, where there is genuinely nothing to account for.
    usage: Optional[ModelUsage] = None

    @property
    def tool_calls(self) -> int:
        return self.tool_context.call_count


class AgentRuntime:
    """Builds and runs the agent. The only place a model is invoked."""

    def __init__(
        self,
        kb: KnowledgeBase,
        model=None,
        *,
        max_tool_calls: int = MAX_TOOL_CALLS,
    ) -> None:
        self.kb = kb
        self.model = model
        self.max_tool_calls = max_tool_calls
        self.rules = RuleExtractor()
        self.template = TemplateComposer()
        # Probed on first use and remembered. See `_with_limits`.
        self._pre_count_tokens = True
        self._limit_note: Optional[str] = None

    # ---- Limits ----------------------------------------------------------

    @staticmethod
    def usage_limits(
        max_tool_calls: int = MAX_TOOL_CALLS,
        *,
        pre_count_tokens: bool = True,
        request_limit: int = config.LLM_REQUEST_LIMIT,
        total_tokens_limit: int = config.LLM_TOTAL_TOKEN_LIMIT,
        output_tokens_limit: int = config.LLM_OUTPUT_TOKEN_LIMIT,
        per_request_input_tokens_limit: int = config.LLM_PER_REQUEST_INPUT_TOKEN_LIMIT,
        cost_limit: Decimal = config.LLM_COST_LIMIT_USD,
    ):
        """Hard caps on one run.

        `count_tokens_before_request` stops an over-budget request **before** it is
        sent, so a runaway loop costs nothing rather than costing the most. Not every
        provider implements it, which is why it is a flag and why the caller degrades
        rather than failing — see `_with_limits`.
        """
        return UsageLimits(
            tool_calls_limit=max_tool_calls,
            request_limit=request_limit,
            total_tokens_limit=total_tokens_limit,
            output_tokens_limit=output_tokens_limit,
            per_request_input_tokens_limit=per_request_input_tokens_limit,
            cost_limit=cost_limit,
            count_tokens_before_request=pre_count_tokens,
        )

    def _limits(self):
        return self.usage_limits(
            self.max_tool_calls, pre_count_tokens=self._pre_count_tokens
        )

    def _with_limits(self, run):
        """Run with pre-request token counting, degrading to post-hoc limits if the
        provider does not support it.

        Worth the extra branch: without it, a provider that cannot count tokens ahead
        of a request fails *every* call rather than merely losing one cost guard. The
        capability is probed once and remembered.
        """
        try:
            return run(self._limits())
        except NotImplementedError as error:
            if "token" not in str(error).lower() or not self._pre_count_tokens:
                raise
            self._pre_count_tokens = False
            self._limit_note = (
                "this provider cannot count tokens before a request; tool and request "
                "caps still apply, but they are enforced after each call rather than "
                "before it"
            )
            return run(self._limits())

    # ---- Segment 1: observe ---------------------------------------------

    def observe(
        self,
        text: str,
        *,
        opportunity=None,
        context: Optional[list] = None,
    ) -> Observation:
        window = build_context(context if context is not None else
                              (opportunity.messages if opportunity else []))
        tool_context = ToolContext(kb=self.kb, opportunity=opportunity)

        if self.model is None:
            outcome = self.rules.extract(text, context=window)
            outcome.degraded = True
            # The one expected degradation: no model was asked for, so none failing is
            # not news. Still reported as degraded on the wire, just not warned about.
            outcome.by_design = True
            outcome.degradation_reason = (
                "no model configured; observations came from the rule-based peer"
            )
            return Observation(extraction=outcome, tool_context=tool_context)

        began = time.perf_counter()
        try:
            result, prompt = self._run_observing_agent(text, window, tool_context)
        except Exception as error:
            outcome = self.rules.extract(text, context=window)
            outcome.degraded = True
            outcome.degradation_reason = (
                f"model extraction failed ({type(error).__name__}: {error}); "
                "fell back to the rule-based peer"
            )
            return Observation(extraction=outcome, tool_context=tool_context)

        elapsed_ms = int(round((time.perf_counter() - began) * 1000))
        detection = schema.to_detection(result.output)
        violations = list(tool_context.violations)
        usage = from_result(
            result,
            purpose="extraction",
            duration_ms=elapsed_ms,
            configured_model=self._configured_model_name(),
            # The prompt that was actually sent, carried back from the call rather
            # than rebuilt here. A telemetry record of a *recomputed* prompt is only
            # accurate for as long as the builder stays pure, and the point of the
            # record is to show what went over the wire.
            input_text=prompt,
            output_text=repr(result.output),
        )
        # A bad tool argument is not a failure of the run, but it is not nothing
        # either: the model was told something it should have known.
        reasons = [violation.describe() for violation in violations]
        if usage is None:
            # Unmeasured is not free. A call that really happened but cannot be
            # accounted for has to be visible, or the run reports a confident zero.
            reasons.append(
                "the model answered but its token usage could not be read, so this "
                "call is missing from the run's cost accounting"
            )

        return Observation(
            extraction=ExtractionOutcome(
                detection=detection,
                source="llm",
                tool_calls=tool_context.call_count,
                violations=violations,
                degraded=bool(reasons),
                degradation_reason="; ".join(reasons) or None,
            ),
            tool_context=tool_context,
            history=list(result.all_messages()),
            usage=usage,
        )

    def _configured_model_name(self) -> str:
        """The name we asked for, as a fallback when the provider does not say.

        Only used for pricing attribution, so a miss costs a cost figure rather than
        a reply. `TestModel` and friends expose no name at all.
        """
        for attribute in ("model_name", "_model_name", "name"):
            value = getattr(self.model, attribute, None)
            if isinstance(value, str) and value:
                return value
        return ""

    def _run_observing_agent(self, text: str, window: list, tool_context: ToolContext):
        agent = Agent(
            self.model,
            deps_type=ToolContext,
            output_type=schema.ExtractionOutput,
            system_prompt=policy.extraction_system_prompt(),
        )

        # Thin wrappers. The tool logic itself is plain functions taking a context, so
        # every tool stays callable and testable with no framework in scope.
        @agent.tool
        def lookup_product_fact(
            ctx: RunContext[ToolContext], product: str, field: str
        ) -> str:
            """Look up one approved fact. Field uses exact schema values such as premium, waiting_period, coverage, claims, or payment."""
            chosen_product, error = ctx.deps.coerce(product, Product, "product")
            if error:
                return error
            chosen_field, error = ctx.deps.coerce(field, KnowledgeField, "field")
            if error:
                return error
            return knowledge_tools.lookup_product_fact(
                ctx.deps, chosen_product, chosen_field
            )

        @agent.tool
        def compare_products(
            ctx: RunContext[ToolContext], field: str, products: list[str]
        ) -> str:
            """Compare plans. Field uses an exact schema value such as premium, waiting_period, coverage, claims, or payment."""
            chosen_field, error = ctx.deps.coerce(field, KnowledgeField, "field")
            if error:
                return error
            chosen: list[Product] = []
            for raw in products:
                member, error = ctx.deps.coerce(raw, Product, "products")
                if error:
                    return error
                chosen.append(member)
            return knowledge_tools.compare_products(ctx.deps, chosen_field, chosen)

        @agent.tool
        def list_products(ctx: RunContext[ToolContext]) -> str:
            """List every CareSure plan with its positioning."""
            return knowledge_tools.list_products(ctx.deps)

        @agent.tool
        def conversation_summary(ctx: RunContext[ToolContext]) -> str:
            """Recall who this customer is and what has been discussed."""
            return opportunity_tools.conversation_summary(ctx.deps)

        @agent.tool
        def request_human_handoff(ctx: RunContext[ToolContext], reason: str) -> str:
            """Propose that a human representative takes over, with a reason."""
            return handoff_tools.request_human_handoff(ctx.deps, reason)

        prompt = self._observing_prompt(text, window)
        result = self._with_limits(
            lambda limits: agent.run_sync(
                prompt, deps=tool_context, usage_limits=limits
            )
        )
        # The prompt travels back with the result so telemetry records what was sent.
        return result, prompt

    @staticmethod
    def _observing_prompt(text: str, window: list) -> str:
        parts = []
        if window:
            transcript = "\n".join(
                f"{'customer' if message.is_from_customer else 'assistant'}: "
                f"{message.text}"
                for message in window
            )
            parts.append(policy.data_section("recent conversation", transcript))
        parts.append(policy.data_section("the customer's latest message", text))
        parts.append("Report what you observe in this latest message.")
        return "\n\n".join(parts)

    # ---- Segment 2: compose ---------------------------------------------

    def compose(
        self,
        observation: Observation,
        *,
        action: NextBestAction,
        facts: list[str],
        customer_name: str = "",
        concern: Optional[str] = None,
        disclaimer: Optional[str] = None,
    ) -> ReplyOutcome:
        """Word the reply, continuing the observing segment's conversation."""
        request = ReplyRequest(
            facts=facts,
            action=action,
            customer_name=customer_name,
            concern=concern,
            disclaimer=disclaimer if disclaimer is not None else self.kb.disclaimer,
            history=continuity_history(observation.history),
        )
        if self.model is None:
            return self.template.compose(request)
        return ModelComposer(
            self.model, fallback=self.template, usage_limits=self._limits()
        ).compose(request)
