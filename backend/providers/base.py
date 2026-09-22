# -*- coding: utf-8 -*-
"""What a provider resolves to: a description, never a client.

`resolve()` returns a `ProviderSpec` — the endpoint, the model name, the credential
and the timeout, or the reason there is nothing to call. It deliberately does **not**
return a constructed model object, because building one means importing the agent
framework, and §4 rule 2 of `docs/backend-plan.md` gives that import to `agent/` and
to no one else. `agent.model_factory` turns a spec into something callable.

The split is worth stating plainly, because the two halves are easy to confuse:

    providers/   decides *what* to talk to, and can say "nothing, because ..."
    agent/       decides *how* to talk to it, and is the only framework owner

`is_offline` is a first-class outcome, not a failure. The whole pipeline completes
with no model: rule-based understanding, template replies, every one of them marked
`generation="template"`, and `/health` reporting `degraded: true`. A demo that dies
because a key is missing is worse than one that runs visibly offline.

Every refusal carries a `reason` in plain language. "Offline" with no explanation is
the failure mode this rebuild exists to remove — somebody would otherwise spend an
afternoon wondering why the model is never called.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# Where an OpenAI-compatible endpoint keeps chat completions. Protocol knowledge,
# which this package owns; the framework normally hides it, but `probe` speaks the
# protocol directly so that it can test the endpoint rather than the framework.
CHAT_COMPLETIONS_PATH = "/chat/completions"
OPENAI_DEFAULT_BASE_URL = "https://api.openai.com/v1"


@dataclass(frozen=True)
class ProviderSpec:
    """How to reach a model, or why there is not one to reach."""

    provider: str
    model_name: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    timeout: float = 30.0
    max_tool_steps: int = 6
    reason: str = ""

    @property
    def is_offline(self) -> bool:
        return self.provider == "offline"

    @property
    def endpoint(self) -> str:
        """The absolute chat-completions URL this spec points at.

        Providers differ on whether the version path belongs in the configured base
        URL, so a missing `/v1` is the single most common misconfiguration here. This
        does not guess: it appends nothing but the completions path, and `probe`
        reports a 404 with that fact attached.
        """
        base = (self.base_url or OPENAI_DEFAULT_BASE_URL).rstrip("/")
        return base + CHAT_COMPLETIONS_PATH

    def describe(self) -> str:
        """A one-line summary that never contains the key."""
        if self.is_offline:
            return f"offline - {self.reason}"
        where = self.base_url or f"{OPENAI_DEFAULT_BASE_URL} (provider default)"
        return f"{self.provider}: {self.model_name} via {where}"
