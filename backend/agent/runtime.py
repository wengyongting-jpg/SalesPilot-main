# -*- coding: utf-8 -*-
"""Agent construction: the framework seam.

If `pydantic_ai` is ever replaced, this is the only module that changes
(`docs/backend-plan.md` §5's go/no-go). `extraction/`, `reply/`, `tools/`,
`schema.py` and `policy.py` talk to a `pydantic_ai.models.Model` object or to
`None` (the offline path) — none of them construct one directly.
"""
from __future__ import annotations

from typing import Optional

from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from .. import config
from ..providers.openai_compatible import from_config


def build_model() -> Optional[Model]:
    """The configured model, or `None` to select the offline (rules/template) path.

    `None` is returned — not raised — whenever there is nothing to call: the
    provider is explicitly `offline`, or no API key is configured. Both are
    first-class, supported outcomes (`backend/providers/offline.py`), not
    errors.
    """
    if config.LLM_PROVIDER == "offline":
        return None
    cfg = from_config()
    if not cfg.api_key:
        return None
    provider = OpenAIProvider(base_url=cfg.base_url, api_key=cfg.api_key)
    return OpenAIChatModel(cfg.model, provider=provider)
