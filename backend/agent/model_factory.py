# -*- coding: utf-8 -*-
"""Turn a `ProviderSpec` into something the runtime can call.

This is the **only** module in the backend that constructs a model object, which is
what keeps §4 rule 2 of `docs/backend-plan.md` true and executable: the agent
framework is an implementation detail of `agent/`, and
`backend/tests/test_architecture.py` fails the build if the import appears anywhere
else. `providers/` decides *what* to talk to and stays framework-free; this decides
*how*.

`build()` never raises. Every way of failing to get a model returns `None` together
with a reason, because the offline path is a working peer rather than a fallback: a
missing key, an uninstalled dependency and a malformed base URL should all produce a
backend that starts and answers, visibly degraded.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from ..providers import ProviderSpec
from ..providers import offline


@dataclass(frozen=True)
class BuiltModel:
    """A callable model, or `None` plus the reason there is not one."""

    model: Optional[Any]
    spec: ProviderSpec
    reason: str

    @property
    def is_offline(self) -> bool:
        return self.model is None

    def describe(self) -> str:
        if self.is_offline:
            return f"offline - {self.reason}"
        return self.spec.describe()


def build(spec: Optional[ProviderSpec] = None) -> BuiltModel:
    """Construct the model described by `spec`, or explain why it cannot be."""
    if spec is None:
        from ..providers import resolve

        spec = resolve()

    if spec.is_offline:
        return BuiltModel(model=None, spec=spec, reason=spec.reason)

    try:
        from pydantic_ai.models.openai import OpenAIChatModel
        from pydantic_ai.providers.openai import OpenAIProvider
    except ImportError as error:
        return BuiltModel(
            model=None,
            spec=spec,
            reason=f"{offline.FRAMEWORK_MISSING} [{error}]",
        )

    try:
        # An explicit timeout rather than the client default. A provider that hangs
        # must degrade this one message, not hold the request open indefinitely --
        # there is a customer waiting on a reply.
        #
        # `httpx2` in preference to `httpx`: passing the latter to an
        # OpenAI-compatible provider is deprecated and goes away in pydantic-ai v3,
        # and it emits a warning on every startup. The fallback is kept because the
        # package arrives transitively with the OpenAI client rather than being
        # pinned here, so it is not this module's place to assume it is present.
        http_client = _async_client(spec.timeout)
        provider = (
            OpenAIProvider(
                base_url=spec.base_url,
                api_key=spec.api_key,
                http_client=http_client,
            )
            if spec.base_url
            else OpenAIProvider(api_key=spec.api_key, http_client=http_client)
        )
        model = OpenAIChatModel(spec.model_name, provider=provider)
        # An OpenAI-compatible gateway hides the upstream provider identity from the
        # framework price lookup. Attach our reviewed price table so `cost_limit` is
        # an enforced limit, not a warning followed by unbounded spend.
        from ..observability import pricing
        if pricing.is_known(spec.model_name):
            from .costed_model import CostedGatewayModel
            model = CostedGatewayModel(model)
    except Exception as error:
        # Construction failing is a configuration problem, and the right response is
        # still to run rather than to refuse to start.
        return BuiltModel(
            model=None,
            spec=spec,
            reason=(
                f"could not construct the model for {spec.describe()} "
                f"({type(error).__name__}: {error})"
            ),
        )

    return BuiltModel(model=model, spec=spec, reason="configured")


def _async_client(timeout: float):
    """An async HTTP client with our timeout, from whichever httpx is available."""
    try:
        import httpx2

        return httpx2.AsyncClient(timeout=timeout)
    except ImportError:
        import httpx

        return httpx.AsyncClient(timeout=timeout)
