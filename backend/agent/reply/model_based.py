# -*- coding: utf-8 -*-
"""Model-composed reply wording, grounded in the supplied facts.

Continues the observing segment's conversation rather than starting a new one, so the
model still has its own tool calls and their results in view when it writes. See
`docs/backend-plan.md` §3.

No tools are offered in this segment. By the time it runs, everything that needed
looking up has been looked up and the kernel has decided; a tool call here would only
be a second chance to change an answer that has already been settled.

On failure it delegates to the template peer and **says that it did**. That is the
distinction from the frozen build, which caught every exception, silently fell back,
and left no trace beyond one response field nobody watched.
"""
from __future__ import annotations

import time
from typing import Optional

from pydantic_ai import Agent

from ...domain.enums import Generation
from .. import policy
from ..usage import from_result
from . import ReplyOutcome, ReplyRequest
from .template import TemplateComposer


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
        prompt = policy.build_reply_prompt(
            facts=request.facts,
            action=request.action,
            customer_name=request.customer_name,
            concern=request.concern,
        )
        began = time.perf_counter()
        try:
            agent = Agent(
                self.model,
                output_type=str,
                system_prompt=policy.reply_system_prompt(request.disclaimer),
            )
            result = agent.run_sync(
                prompt,
                message_history=request.history or None,
                usage_limits=self.usage_limits,
            )
            text = (result.output or "").strip()
            if not text:
                raise ValueError("the model returned an empty reply")
            elapsed_ms = int(round((time.perf_counter() - began) * 1000))
            usage = from_result(
                result,
                purpose="response_generation",
                duration_ms=elapsed_ms,
                input_text=prompt,
                output_text=text,
            )
            return ReplyOutcome(
                text=text,
                generation=Generation.LLM,
                history=list(result.all_messages()),
                usage=usage,
                # A reply that cannot be accounted for is still a reply, but the run
                # must not report its cost as zero without saying why.
                degraded=usage is None,
                degradation_reason=(
                    None if usage is not None else
                    "the model wrote the reply but its token usage could not be "
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
