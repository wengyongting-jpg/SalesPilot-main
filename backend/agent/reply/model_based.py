# -*- coding: utf-8 -*-
"""Model-selected facts, rendered as customer-safe deterministic wording.

Continues the observing segment's conversation rather than starting a new one, so the
model can select relevant approved facts using the customer's latest request. See
`docs/v0.0/backend/backend-plan.md` §3.

No tools are offered in this segment. The model returns indices, not prose. The
existing template peer renders the selected facts, preventing unsupported claims.

On failure it delegates to the template peer and **says that it did**. That is the
distinction from the frozen build, which caught every exception, silently fell back,
and left no trace beyond one response field nobody watched.
"""
from __future__ import annotations

import json
import time
from typing import Optional

from pydantic_ai import Agent
from pydantic import BaseModel, Field
from pydantic_ai.usage import UsageLimits

from ... import config
from ...domain.enums import Generation
from .. import policy
from ..usage import from_result
from . import ReplyOutcome, ReplyRequest
from .template import TemplateComposer


class FactSelection(BaseModel):
    fact_indices: list[int] = Field(default_factory=list)
    template_id: str = Field(default="", description="One permitted reply template ID")
    acknowledgement_id: str = Field(
        default="none", description="One permitted short acknowledgement ID"
    )


class ModelComposer:
    def __init__(
        self,
        model,
        *,
        fallback: Optional[TemplateComposer] = None,
        usage_limits=None,
    ) -> None:
        self.model = model
        self.fallback = fallback or TemplateComposer()
        self.usage_limits = usage_limits or UsageLimits(
            request_limit=1,
            tool_calls_limit=0,
            total_tokens_limit=config.LLM_TOTAL_TOKEN_LIMIT,
            output_tokens_limit=config.LLM_OUTPUT_TOKEN_LIMIT,
            per_request_input_tokens_limit=config.LLM_PER_REQUEST_INPUT_TOKEN_LIMIT,
            cost_limit=config.LLM_COST_LIMIT_USD,
            count_tokens_before_request=False,
        )

    def compose(self, request: ReplyRequest) -> ReplyOutcome:
        # No approved fact means no free-text generation or model speculation.
        # A pre-curated enumeration needs no selection either: every fact
        # belongs in the answer, so there's nothing for a model to pick
        # between, and calling one to reach the same "keep everything" result
        # is only cost and latency.
        if not request.facts or not request.select_facts:
            return self.fallback.compose(request)
        if not request.model_allowed:
            fallback = self.fallback.compose(request)
            return ReplyOutcome(
                text=fallback.text,
                generation=Generation.TEMPLATE,
                displayed_facts=fallback.displayed_facts,
                degraded=True,
                degradation_reason=(
                    request.model_budget_reason
                    or "model reply skipped because the customer-turn budget is exhausted"
                ),
                history=list(request.history or []),
            )
        prompt = policy.build_fact_selection_prompt(
            facts=request.facts,
            customer_text=request.customer_text,
            concern=request.concern,
            history=request.history,
            memory=request.memory,
            template_ids=self.fallback.template_ids_for(request.action.reply_mode),
            template_descriptions=self.fallback.template_descriptions_for(
                request.action.reply_mode
            ),
        )
        system_prompt = policy.fact_selection_system_prompt()
        estimated_input_tokens = policy.estimate_prompt_tokens(
            prompt + "\n\n" + system_prompt
        ) + 256  # reserve room for structured-output schema instructions
        if estimated_input_tokens > config.LLM_PER_REQUEST_INPUT_TOKEN_LIMIT:
            fallback = self.fallback.compose(request)
            return ReplyOutcome(
                text=fallback.text,
                generation=Generation.TEMPLATE,
                displayed_facts=fallback.displayed_facts,
                degraded=True,
                degradation_reason=(
                    "reply model skipped because the bounded conversation context "
                    "and instructions exceed the per-request input limit"
                ),
                history=list(request.history or []),
            )
        began = time.perf_counter()
        try:
            agent = Agent(
                self.model,
                output_type=FactSelection,
                system_prompt=system_prompt,
            )
            # Domain messages are passed as a source-labelled transcript in the
            # user prompt. They are not pydantic-ai ModelMessage instances and
            # cannot safely be supplied through `message_history=`.
            result = agent.run_sync(
                prompt,
                usage_limits=request.usage_limits or self.usage_limits,
            )
            indices = list(dict.fromkeys(
                index for index in result.output.fact_indices
                if 0 <= index < len(request.facts)
            ))[:2]
            # Empty or invalid selection means we cannot support an answer from the
            # offered facts. The renderer says so rather than guessing relevance.
            selected = [request.facts[index] for index in indices]
            safe_request = ReplyRequest(
                facts=selected, action=request.action,
                customer_name=request.customer_name, concern=request.concern,
                customer_text=request.customer_text,
                disclaimer=request.disclaimer, history=request.history,
                memory=request.memory,
                template_id=(
                    result.output.template_id
                    if result.output.template_id in self.fallback.template_ids_for(request.action.reply_mode)
                    else None
                ),
                acknowledgement_id=(
                    result.output.acknowledgement_id
                    if result.output.acknowledgement_id in self.fallback.acknowledgement_ids()
                    else "none"
                ),
                usage_limits=request.usage_limits,
                model_allowed=request.model_allowed,
                model_budget_reason=request.model_budget_reason,
            )
            rendered = self.fallback.compose(safe_request)
            elapsed_ms = int(round((time.perf_counter() - began) * 1000))
            usage = from_result(
                result,
                purpose="response_generation",
                duration_ms=elapsed_ms,
                input_text=prompt,
                output_text=json.dumps(result.output.model_dump(exclude_unset=True)),
            )
            return ReplyOutcome(
                text=rendered.text,
                # The wording is the deterministic renderer's, but a live model
                # call chose which approved facts to use — the customer-facing
                # `generation` field means "did a model participate this turn",
                # not "did a model author every word", so this is `LLM`, not
                # `TEMPLATE`. `interface-v1.md` §5.7 and every other composer in
                # this codebase report it on that same basis.
                generation=Generation.LLM,
                displayed_facts=rendered.displayed_facts,
                history=list(result.all_messages()),
                usage=usage,
                degraded=usage is None,
                degradation_reason=(
                    None if usage is not None else
                    "the model selected facts but its token usage could not be "
                    "read, so this call is missing from the run's cost accounting"
                ),
            )
        except Exception as error:  # provider, network, key, limit or empty output
            degraded = self.fallback.compose(request)
            return ReplyOutcome(
                text=degraded.text,
                generation=Generation.TEMPLATE,
                displayed_facts=degraded.displayed_facts,
                degraded=True,
                degradation_reason=(
                    f"model reply failed ({type(error).__name__}: {error}); "
                    "composed from a template instead"
                ),
                history=list(request.history or []),
            )
