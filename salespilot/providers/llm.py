# -*- coding: utf-8 -*-
"""LLM provider abstraction.

Implementations:
- StubLLMClient: offline placeholder; raises UnavailableLLMError on use.
- OpenAICompatibleLLMClient: any OpenAI-compatible chat completions endpoint
  (imports the `openai` package lazily so it is not a hard dependency).

Configure via environment variables (see salespilot.config):
    SALESPILOT_LLM=openai
    SALESPILOT_LLM_MODEL=gpt-4o-mini
    SALESPILOT_LLM_BASE_URL=https://...   # optional, for compatible gateways
    SALESPILOT_LLM_API_KEY=sk-...         # or OPENAI_API_KEY
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from .. import config


class UnavailableLLMError(RuntimeError):
    """Raised when generation is requested but no LLM backend is configured."""


class LLMClient(ABC):
    @abstractmethod
    def generate(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.2,
        max_tokens: int = 600,
    ) -> str:
        """Generate an assistant reply from a chat message list.

        `messages` follows the OpenAI chat shape:
            [{"role": "system"|"user"|"assistant", "content": "..."}]
        """
        raise NotImplementedError


class StubLLMClient(LLMClient):
    """Default offline client. It never calls an external service."""

    def generate(self, messages, *, temperature=0.2, max_tokens=600) -> str:
        raise UnavailableLLMError(
            "No LLM provider configured. Set SALESPILOT_LLM=openai and an API "
            "key, or keep using the rule-based response generator."
        )


class OpenAICompatibleLLMClient(LLMClient):
    """OpenAI-compatible chat client; the `openai` package is imported lazily."""

    def __init__(
        self,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> None:
        self.model = model or config.LLM_MODEL
        self.api_key = api_key or config.LLM_API_KEY
        self.base_url = base_url or config.LLM_API_BASE
        self._client = None  # lazily initialised

    def _get_client(self):
        if self._client is None:
            if not self.api_key:
                raise UnavailableLLMError(
                    "LLM provider selected but no API key was found "
                    "(SALESPILOT_LLM_API_KEY / OPENAI_API_KEY)."
                )
            try:
                from openai import OpenAI  # Imported only when actually used
            except ImportError as exc:  # pragma: no cover - depends on env
                raise UnavailableLLMError(
                    "The 'openai' package is not installed. Run "
                    "`py -3 -m pip install openai` or use the stub provider."
                ) from exc
            kwargs = {"api_key": self.api_key}
            if self.base_url:
                kwargs["base_url"] = self.base_url
            self._client = OpenAI(**kwargs)
        return self._client

    def generate(self, messages, *, temperature=0.2, max_tokens=600) -> str:
        client = self._get_client()
        response = client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content or ""


def build_llm_client(provider: Optional[str] = None) -> LLMClient:
    """Factory selecting a client from configuration (defaults to the stub)."""
    selected = (provider or config.LLM_PROVIDER or "stub").lower()
    if selected in ("openai", "gateway"):
        # "gateway" uses the Hackathon LLM Gateway URL if configured
        return OpenAICompatibleLLMClient()
    if selected == "stub":
        return StubLLMClient()
    raise ValueError(f"Unknown LLM provider: {selected!r}")
