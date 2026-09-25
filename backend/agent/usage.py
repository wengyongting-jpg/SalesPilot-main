# -*- coding: utf-8 -*-
"""What one model call actually consumed.

The gap this closes was invisible for a long time and is worth stating plainly.
`observability.recorder.record_llm_call` existed and was thoroughly tested, but
nothing on the live path ever called it: the runtime never reported what a call cost,
so a run through a real provider reported `llm_call_count: 0`, `total_tokens: 0` and
`cost: {"amount": 0.0, "pricing_known": true}`. That last field is the damaging part.
It does not say "unmeasured", it asserts the price is known and the spend was
precisely nothing, while two paid requests had just been made.

The reason no test caught it: the recorder was exercised without its caller, and the
only service-level assertion about `llm_call_count` ran on the offline path, where
zero is the correct answer.

This type is deliberately framework-free - plain integers and strings read off a
result object by attribute. `agent` is allowed to import the framework, but `services`
is not, and `services` is what does the recording. Handing it a plain value keeps that
boundary intact.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class ModelUsage:
    """One model call, as the recorder needs it."""

    purpose: str
    model: str
    duration_ms: int
    prompt_tokens: int
    completion_tokens: int
    requests: int = 1
    input_text: str = ""
    output_text: str = ""

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


def from_result(
    result: Any,
    *,
    purpose: str,
    duration_ms: int,
    configured_model: str = "",
    input_text: str = "",
    output_text: str = "",
) -> Optional[ModelUsage]:
    """Read usage off an agent result, or return None if it cannot be read.

    Never raises. A change in the framework's usage API must cost the run its cost
    figure, not the customer their reply - but it must not cost it silently either,
    which is why `None` here makes the step report a degradation rather than
    substituting a confident zero.

    The model name is taken from the provider's own response when it offers one. A
    gateway may serve something other than what was asked for, and the *served* model
    is the one that determines the price.
    """
    usage = getattr(result, "usage", None)
    if usage is None:
        return None
    prompt_tokens = getattr(usage, "input_tokens", None)
    completion_tokens = getattr(usage, "output_tokens", None)
    if prompt_tokens is None and completion_tokens is None:
        return None

    return ModelUsage(
        purpose=purpose,
        model=_model_name(result) or configured_model or "unknown",
        duration_ms=duration_ms,
        prompt_tokens=int(prompt_tokens or 0),
        completion_tokens=int(completion_tokens or 0),
        requests=int(getattr(usage, "requests", 1) or 1),
        input_text=input_text,
        output_text=output_text,
    )


def _model_name(result: Any) -> str:
    """The model the provider says answered, from the last response in the run."""
    try:
        for message in reversed(result.all_messages()):
            name = getattr(message, "model_name", None)
            if name:
                return str(name)
    except Exception:
        return ""
    return ""
