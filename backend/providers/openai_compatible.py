# -*- coding: utf-8 -*-
"""Connection configuration for any OpenAI-compatible endpoint.

This module holds plain data only — base URL, model name, key, timeout — and
imports neither `pydantic_ai` nor `openai`. Constructing the actual framework
model object is `agent/runtime.py`'s job: `backend/tests/test_architecture.py`
confines those two frameworks to the `agent` package, and this module is not
part of it. If the organiser gateway turns out not to be OpenAI-compatible,
this is the only module that changes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .. import config


@dataclass(frozen=True)
class OpenAICompatibleConfig:
    model: str
    api_key: Optional[str]
    base_url: Optional[str]
    timeout_seconds: float


def from_config() -> OpenAICompatibleConfig:
    return OpenAICompatibleConfig(
        model=config.LLM_MODEL,
        api_key=config.LLM_API_KEY,
        base_url=config.LLM_API_BASE,
        timeout_seconds=config.LLM_TIMEOUT_SECONDS,
    )
