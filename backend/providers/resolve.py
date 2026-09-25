# -*- coding: utf-8 -*-
"""Turn configuration into a `ProviderSpec`, or into a stated reason for offline.

One module covers OpenAI, the organiser's gateway, and anything else speaking the
OpenAI chat-completions protocol, because the only difference between them is a base
URL. **This is the adapter seam**: if the organiser's endpoint turns out to speak some
other protocol, a sibling module here resolves to a different spec and `probe` learns
a second dialect — nothing above this package changes, because everything above it
receives a description rather than a client.

No third-party import appears in this file. That is the point of the split: see
`base.py` for why constructing the model belongs to `agent/`.
"""
from __future__ import annotations

from typing import Optional

from .. import config
from . import offline
from .base import ProviderSpec

OFFLINE_NAMES = ("offline", "", "stub", "none")


def resolve(
    *,
    provider: Optional[str] = None,
    model_name: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    timeout: Optional[float] = None,
    max_tool_steps: Optional[int] = None,
) -> ProviderSpec:
    """Decide which model to use, reading configuration unless told otherwise.

    Every argument defaults to the corresponding setting. They exist so a test can
    resolve a spec without touching the process environment, which is what makes this
    function testable at all.
    """
    provider = (provider if provider is not None else config.LLM_PROVIDER or "offline")
    provider = provider.strip().lower()
    if provider in OFFLINE_NAMES:
        return offline.spec(offline.NO_PROVIDER_SELECTED)

    api_key = api_key if api_key is not None else config.LLM_API_KEY
    if not api_key:
        return offline.spec(offline.NO_API_KEY)

    model_name = model_name if model_name is not None else config.LLM_MODEL
    if not model_name or not model_name.strip():
        return offline.spec(offline.NO_MODEL_NAME)

    return ProviderSpec(
        provider=provider,
        model_name=model_name.strip(),
        base_url=(base_url if base_url is not None else config.LLM_API_BASE) or None,
        api_key=api_key,
        timeout=(
            timeout if timeout is not None else config.LLM_TIMEOUT_SECONDS
        ),
        max_tool_steps=(
            max_tool_steps
            if max_tool_steps is not None
            else config.LLM_MAX_TOOL_STEPS
        ),
        reason="configured",
    )
