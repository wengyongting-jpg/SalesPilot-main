# -*- coding: utf-8 -*-
"""The offline provider spec, and the reasons it gets selected.

Not a broken stand-in. Selecting this on purpose (or falling back to it after a
missing key, a missing model name, or an absent framework) is a first-class,
supported configuration — every message it produces is marked
`generation="template"`, never silently.
"""
from __future__ import annotations

from .base import ProviderSpec

NO_PROVIDER_SELECTED = "no provider configured — offline by default"
NO_API_KEY = "no API key configured"
NO_MODEL_NAME = "no model name configured"
FRAMEWORK_MISSING = "the agent framework (pydantic-ai) is not installed"


def spec(reason: str) -> ProviderSpec:
    """The offline `ProviderSpec`, carrying why it was selected."""
    return ProviderSpec(provider="offline", reason=reason)
