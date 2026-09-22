# -*- coding: utf-8 -*-
"""Reachability probing: what was actually found at startup.

Stdlib only — no framework import, so this can run from `backend/cli.py`
before `agent/` (and `pydantic_ai`) is even imported. A probe failure never
raises; it degrades to a reported reason so `--probe` always exits 0.
"""
from __future__ import annotations

import urllib.error
import urllib.request

from .. import config
from .openai_compatible import OpenAICompatibleConfig, from_config

_DEFAULT_BASE_URL = "https://api.openai.com/v1"
_PROBE_TIMEOUT_SECONDS = 5.0


def probe() -> dict[str, object]:
    """Report the effective model configuration and whether it looks reachable.

    Returns a dict rather than raising, so a caller (the CLI, a startup log
    line) always gets something to print regardless of what went wrong.
    """
    provider = config.LLM_PROVIDER

    if provider == "offline":
        return {
            "provider": "offline",
            "reachable": None,
            "detail": "offline mode — no model configured, deterministic path only",
        }

    cfg = from_config()
    if not cfg.api_key:
        return {
            "provider": provider,
            "reachable": False,
            "detail": "no API key configured — falling back to the offline path",
        }

    reachable, detail = _check_reachable(cfg)
    return {"provider": provider, "reachable": reachable, "detail": detail}


def _check_reachable(cfg: OpenAICompatibleConfig) -> tuple[bool, str]:
    base_url = (cfg.base_url or _DEFAULT_BASE_URL).rstrip("/")
    url = f"{base_url}/models"
    request = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {cfg.api_key}"}
    )
    try:
        with urllib.request.urlopen(
            request, timeout=min(cfg.timeout_seconds, _PROBE_TIMEOUT_SECONDS)
        ) as response:
            status = response.status
    except urllib.error.HTTPError as exc:
        # A 4xx/5xx still proves the endpoint is reachable — the key or path
        # may be wrong, but there is something OpenAI-compatible listening.
        return exc.code < 500, f"HTTP {exc.code} from {url}"
    except Exception as exc:  # noqa: BLE001 — any transport failure is "unreachable"
        return False, f"{type(exc).__name__}: {exc}"
    return status < 500, f"HTTP {status} from {url}"
