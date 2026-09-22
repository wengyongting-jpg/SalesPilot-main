# -*- coding: utf-8 -*-
"""The offline spec: no model, stated as a decision rather than a fault.

There is no client here and nothing to stub. `agent.runtime` takes `model=None` and
runs its rule-based and template peers, which are peer implementations of the same
protocols rather than fallbacks — see `backend/agent/extraction/__init__.py` for why
that distinction was the fix for this project's worst defect.

This module exists so the reason for being offline has somewhere to live. A provider
that silently does nothing is indistinguishable from a broken one.
"""
from __future__ import annotations

from .base import ProviderSpec

NO_PROVIDER_SELECTED = (
    "SALESPILOT_LLM is offline, so no model is called. Rule-based understanding and "
    "template replies are used, and every reply is marked generation=template."
)

NO_API_KEY = (
    "a provider is selected but SALESPILOT_LLM_API_KEY is empty. Running offline "
    "rather than failing every message. Put the key in .env - see .env.example."
)

NO_MODEL_NAME = (
    "a provider and key are set but SALESPILOT_LLM_MODEL is empty. Running offline "
    "rather than sending a request no endpoint can route."
)

FRAMEWORK_MISSING = (
    "the agent framework is not installed, so no model can be constructed. Run "
    "`py -3 -m pip install -r requirements.txt`."
)


def spec(reason: str) -> ProviderSpec:
    return ProviderSpec(provider="offline", reason=reason)
