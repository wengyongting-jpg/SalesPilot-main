# -*- coding: utf-8 -*-
"""Model-selected facts, rendered as customer-safe deterministic wording.

Continues the observing segment's conversation rather than starting a new one, so the
model can select relevant approved facts using the customer's latest request. See
`docs/backend-plan.md` §3.

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

from ...domain.enums import Generation
from .. import policy
from ..usage import from_result
from . import ReplyOutcome, ReplyRequest
from .template import TemplateComposer


class FactSelection(BaseModel):
    fact_indices: list[int] = Field(default_factory=list)


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
        self.usage_limits = usage_limits

    def compose(self, request: ReplyRequest) -> ReplyOutcome:
        # No approved fact means no free-text generation or model speculation.
        if not request.facts:
            return self.fallback.compose(request)
        prompt = policy.build_fact_selection_prompt(
            facts=request.facts, concern=request.concern
        )
        began = time.perf_counter()
        try:
            agent = Agent(
                self.model,
                output_type=FactSelection,
                system_prompt=policy.fact_selection_system_prompt(),
            )
            result = agent.run_sync(
                prompt,
                message_history=request.history or None,
                usage_limits=self.usage_limits,
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
                disclaimer=request.disclaimer, history=request.history,
            )
            rendered = self.fallback.compose(safe_request)
            elapsed_ms = int(round((time.perf_counter() - began) * 1000))
            usage = from_result(
                result,
                purpose="response_generation",
                duration_ms=elapsed_ms,
                input_text=prompt,
                output_text=json.dumps(result.output.model_dump()),
            )
            return ReplyOutcome(
                text=rendered.text,
                generation=Generation.TEMPLATE,
                history=list(result.all_messages()),
                usage=usage,
                # Selection ran through the model; the words came from the approved
                # facts and the existing deterministic renderer.
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
                degraded=True,
                degradation_reason=(
                    f"model reply failed ({type(error).__name__}: {error}); "
                    "composed from a template instead"
                ),
                history=list(request.history or []),
            )
