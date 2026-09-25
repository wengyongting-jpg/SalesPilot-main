# -*- coding: utf-8 -*-
"""Per-customer-turn model budgets shared by extraction and reply selection."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from pydantic_ai.usage import UsageLimits

from .. import config
from ..observability.recorder import RunRecorder


@dataclass(frozen=True)
class ModelBudget:
    allowed: bool
    limits: Optional[UsageLimits]
    reason: Optional[str] = None


def for_turn(
    recorder: Optional[RunRecorder], *, allow_tools: bool,
) -> ModelBudget:
    """Return only the remaining configured allowance for this customer turn."""
    calls = recorder.llm_calls if recorder else []
    tool_calls = recorder.tool_calls if recorder else []
    spent_tokens = sum(call.total_tokens for call in calls)
    spent_cost = sum(
        (call.cost.amount for call in calls if call.cost is not None),
        Decimal("0"),
    )
    requests_left = config.LLM_REQUEST_LIMIT - len(calls)
    tokens_left = config.LLM_TOTAL_TOKEN_LIMIT - spent_tokens
    cost_left = config.LLM_COST_LIMIT_USD - spent_cost
    tools_left = config.LLM_MAX_TOOL_STEPS - len(tool_calls) if allow_tools else 0

    if requests_left <= 0:
        return ModelBudget(False, None, "turn request limit exhausted")
    if tokens_left <= 0:
        return ModelBudget(False, None, "turn token limit exhausted")
    if cost_left <= 0:
        return ModelBudget(False, None, "turn cost limit exhausted")

    return ModelBudget(
        True,
        UsageLimits(
            request_limit=requests_left,
            tool_calls_limit=max(0, tools_left),
            total_tokens_limit=tokens_left,
            output_tokens_limit=config.LLM_OUTPUT_TOKEN_LIMIT,
            per_request_input_tokens_limit=config.LLM_PER_REQUEST_INPUT_TOKEN_LIMIT,
            cost_limit=cost_left,
            count_tokens_before_request=False,
        ),
    )
