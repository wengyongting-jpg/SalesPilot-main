"""Attach server-owned prices to OpenAI-compatible gateway responses.

Pydantic AI prices a response from the provider/model pair. An organiser gateway is
reported as ``openai`` even when it serves an AWS Bedrock model, so its otherwise
correct built-in cost guard cannot find a rate. This wrapper fills only missing costs
from SalesPilot's reviewed table; provider-reported costs always win.
"""
from __future__ import annotations

from pydantic_ai.messages import ModelResponse
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.exceptions import UsageLimitExceeded

from ..observability import pricing


class CostedGatewayModel(WrapperModel):
    async def request(self, messages, model_settings, model_request_parameters) -> ModelResponse:
        response = await self.wrapped.request(
            messages, model_settings, model_request_parameters
        )
        if response.usage.cost is None:
            model_name = response.model_name or self.wrapped.model_name
            money = pricing.cost_for(
                model_name,
                response.usage.input_tokens,
                response.usage.output_tokens,
            )
            if money is None:
                # A configured price is not sufficient if the gateway reports a
                # different model or omits token usage. Do not let a cost-limited
                # run continue with an unknown charge.
                raise UsageLimitExceeded(
                    f"Cannot price gateway response from model {model_name!r}"
                )
            response.usage.cost = money.amount
        return response

