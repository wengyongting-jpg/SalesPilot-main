# -*- coding: utf-8 -*-
"""The pydantic-ai → observability translator.

The only module that knows both the framework's message types and the run
record's types. `backend.observability` never imports the framework (enforced
by `test_architecture.py`), so everything a run record needs — per-request
usage, model name, timings, tool calls, prompt and output text — is read from
`result.all_messages()` here and handed over as plain values.

Also classifies failures for `docs/v0.0/backend/backend-plan.md` §7's three classes:
`UNAVAILABLE_ERRORS` is "model unavailable"; `UnexpectedModelBehavior` with a
`ValidationError` cause is "model wrong" (handled by the extraction peer);
anything else is a program error and propagates.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import openai
from pydantic_ai.exceptions import ModelAPIError, UsageLimitExceeded
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    SystemPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from ..observability import RunRecorder

UNAVAILABLE_ERRORS: tuple[type[BaseException], ...] = (
    ModelAPIError,
    UsageLimitExceeded,
    openai.APIError,
)


def describe_unavailable(exc: BaseException) -> str:
    return f"model unavailable: {type(exc).__name__}: {exc}"


def record_trace(
    recorder: RunRecorder,
    messages: list[ModelMessage],
    *,
    purpose: str,
    finished_at: datetime,
) -> None:
    """Record every model request and every model-selected tool call in a trace."""
    for index, message in enumerate(messages):
        if not isinstance(message, ModelResponse):
            continue
        preceding = messages[index - 1] if index > 0 else None
        following = messages[index + 1] if index + 1 < len(messages) else None
        started = _request_time(preceding) or message.timestamp
        ended = _request_time(following) or finished_at
        usage = message.usage
        recorder.llm_call(
            purpose=purpose,
            model=message.model_name or "unknown",
            duration_ms=_ms_between(started, message.timestamp),
            prompt_tokens=usage.input_tokens or 0,
            completion_tokens=usage.output_tokens or 0,
            input_text=_render_request(preceding),
            output_text=_render_response(message),
        )
        for part in message.parts:
            if not isinstance(part, ToolCallPart) or part.tool_name == "final_result":
                continue
            returned = _find_return(following, part)
            recorder.tool_call(
                name=part.tool_name,
                arguments=part.args_as_dict(),
                result_chars=len(_text(returned.content)) if returned else 0,
                duration_ms=_ms_between(message.timestamp, returned.timestamp if returned else ended),
            )


# ---- Helpers ------------------------------------------------------------------


def _request_time(message: ModelMessage | None) -> datetime | None:
    if not isinstance(message, ModelRequest):
        return None
    stamps = [getattr(part, "timestamp", None) for part in message.parts]
    stamps = [s for s in stamps if s is not None]
    return max(stamps) if stamps else None


def _find_return(message: ModelMessage | None, call: ToolCallPart) -> ToolReturnPart | None:
    if not isinstance(message, ModelRequest):
        return None
    for part in message.parts:
        if isinstance(part, ToolReturnPart) and part.tool_call_id == call.tool_call_id:
            return part
    return None


def _ms_between(start: datetime, end: datetime) -> int:
    return max(0, int(round((end - start).total_seconds() * 1000)))


def _render_request(message: ModelMessage | None) -> str:
    if not isinstance(message, ModelRequest):
        return ""
    chunks = []
    for part in message.parts:
        if isinstance(part, SystemPromptPart):
            chunks.append(f"[system] {part.content}")
        elif isinstance(part, UserPromptPart):
            chunks.append(f"[user] {_text(part.content)}")
        elif isinstance(part, ToolReturnPart):
            chunks.append(f"[tool:{part.tool_name}] {_text(part.content)}")
        elif isinstance(part, RetryPromptPart):
            chunks.append(f"[retry] {_text(part.content)}")
    return "\n".join(chunks)


def _render_response(message: ModelResponse) -> str:
    chunks = []
    for part in message.parts:
        if isinstance(part, TextPart):
            chunks.append(part.content)
        elif isinstance(part, ToolCallPart):
            chunks.append(f"[call:{part.tool_name}] {json.dumps(part.args_as_dict(), default=str)}")
    return "\n".join(chunks)


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    try:
        return json.dumps(content, default=str)
    except TypeError:
        return str(content)
