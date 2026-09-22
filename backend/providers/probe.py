# -*- coding: utf-8 -*-
"""Is the configured endpoint actually reachable?

`resolve()` answers "is a model configured". This answers "does it work", which is a
different question and the one that matters five minutes before a demo. It sends the
smallest possible real request and reports what came back.

The distinction it exists to draw is between five states that all look like "offline"
from the outside:

    no provider selected     deliberate; the offline path is running
    no key                   a provider is named but the key is empty
    unreachable              DNS, connection refused, timeout
    rejected                 reached it and it said no - wrong key, wrong model,
                             wrong base URL, or out of quota
    reachable                it answered

`unreachable` and `rejected` are the two worth separating, because they send an
operator to different places: one is the network or the URL, the other is the
credential or the account.

**This speaks HTTP directly, with the standard library only.** Three reasons, and the
third is the one that decided it:

1. A probe should test the endpoint, not the framework. Routing it through
   `pydantic_ai` would mean a framework bug reads as an endpoint failure.
2. It must work when the framework is not installed, since "not installed" is one of
   the states it reports on.
3. `providers/` is framework-free by design (see `base.py`), and a probe that needed
   the framework would have to live somewhere else, away from the configuration it
   is probing.
"""
from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional

from .. import config
from .base import OPENAI_DEFAULT_BASE_URL, ProviderSpec
from .resolve import resolve

# Smallest request that still proves the whole path: authentication, routing to a
# model, and a completion coming back.
_PROBE_BODY = {
    "messages": [{"role": "user", "content": "ok?"}],
    "max_tokens": 5,
    "temperature": 0,
}


@dataclass(frozen=True)
class ProbeResult:
    """What one minimal request found. Never raised, always reportable."""

    reachable: bool
    detail: str
    spec: ProviderSpec
    status: Optional[int] = None
    latency_ms: Optional[int] = None
    model_reply: Optional[str] = None

    @property
    def summary(self) -> str:
        if self.spec.is_offline:
            return f"offline - {self.spec.reason}"
        if self.reachable:
            latency = f"{self.latency_ms}ms" if self.latency_ms is not None else "ok"
            return f"reachable ({latency}) - {self.detail}"
        return f"NOT reachable - {self.detail}"


def probe(
    spec: Optional[ProviderSpec] = None, *, timeout: Optional[float] = None
) -> ProbeResult:
    """Send one minimal request and report the outcome.

    Never raises. A probe that throws would be useless in the place it is most needed,
    which is a command somebody runs when something is already wrong.
    """
    spec = spec if spec is not None else resolve()
    if spec.is_offline:
        return ProbeResult(reachable=False, detail=spec.reason, spec=spec)

    timeout = timeout if timeout is not None else spec.timeout
    body = dict(_PROBE_BODY, model=spec.model_name)
    request = urllib.request.Request(
        spec.endpoint,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {spec.api_key}",
        },
        method="POST",
    )

    began = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read().decode("utf-8", "replace")
            status = response.status
    except urllib.error.HTTPError as error:
        # Reached the endpoint; it answered with a refusal. That is a different
        # diagnosis from not reaching it, so it gets its own branch.
        detail = _explain_http(error, spec)
        return ProbeResult(
            reachable=False, detail=detail, spec=spec, status=error.code,
            latency_ms=_elapsed(began),
        )
    except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as error:
        return ProbeResult(
            reachable=False, detail=_explain_transport(error, spec), spec=spec,
            latency_ms=_elapsed(began),
        )
    except Exception as error:  # pragma: no cover - defence, never a crash
        return ProbeResult(
            reachable=False,
            detail=f"{type(error).__name__}: {str(error)[:200]}",
            spec=spec,
        )

    latency = _elapsed(began)
    reply = _first_message(payload)
    if reply is None:
        # A 200 whose body is not a chat completion means something is answering at
        # that URL, but it is not the API. A proxy login page does exactly this.
        return ProbeResult(
            reachable=False,
            detail=(
                f"HTTP {status} but the body is not a chat completion, so something "
                f"other than the API is answering at {spec.endpoint}. "
                f"[{payload[:160]}]"
            ),
            spec=spec,
            status=status,
            latency_ms=latency,
        )
    return ProbeResult(
        reachable=True,
        detail=f"{spec.model_name} answered",
        spec=spec,
        status=status,
        latency_ms=latency,
        model_reply=reply[:60],
    )


def models(spec: ProviderSpec, *, timeout: float = 15.0) -> tuple[list[str], str]:
    """Ask the endpoint what it can serve. Returns `(names, detail)`.

    `GET /models` is part of the same protocol and is the difference between guessing
    a model name and reading one. An empty list is not an error: plenty of compatible
    gateways do not implement the route, and the caller then falls back to trying a
    name directly.

    Never raises, for the same reason `probe` does not.
    """
    base = (spec.base_url or OPENAI_DEFAULT_BASE_URL).rstrip("/")
    request = urllib.request.Request(
        f"{base}/models",
        headers={"Authorization": f"Bearer {spec.api_key}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as error:
        return [], _explain_http(error, spec)
    except Exception as error:
        return [], f"{type(error).__name__}: {str(error)[:120]}"

    entries = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        return [], "the endpoint answered but not with a model list"
    names = sorted(
        str(entry["id"]) for entry in entries
        if isinstance(entry, dict) and entry.get("id")
    )
    return names, f"{len(names)} models offered"


def _elapsed(began: float) -> int:
    return int(round((time.perf_counter() - began) * 1000))


def _first_message(payload: str) -> Optional[str]:
    """The assistant text from a chat-completions body, or None if it is not one."""
    try:
        data = json.loads(payload)
        content = data["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError):
        return None
    if content is None:
        return ""
    return str(content).strip()


def _explain_http(error: urllib.error.HTTPError, spec: ProviderSpec) -> str:
    """Turn a status code into something actionable.

    A status code tells an operator what broke; this tries to tell them what to do
    about it, which is the difference between a diagnostic and a decoration.
    """
    try:
        body = error.read().decode("utf-8", "replace")[:200]
    except Exception:  # pragma: no cover - the body is a bonus, never required
        body = ""

    code = error.code
    if code in (401, 403):
        return (
            f"HTTP {code}: the endpoint rejected the credential. Check "
            f"SALESPILOT_LLM_API_KEY in .env ({config.redact(spec.api_key)}). "
            f"[{body}]"
        )
    if code == 404:
        return (
            f"HTTP 404: nothing at {spec.endpoint}. Either the model "
            f"{spec.model_name!r} is unknown to this endpoint, or the base URL is "
            f"missing a version path such as /v1. [{body}]"
        )
    if code == 429:
        return f"HTTP 429: rate limited or out of quota. [{body}]"
    if code >= 500:
        return f"HTTP {code}: the endpoint failed on its side. [{body}]"
    return f"HTTP {code}: the endpoint refused the request. [{body}]"


def _explain_transport(error: Exception, spec: ProviderSpec) -> str:
    name = type(error).__name__
    text = str(error)
    lowered = text.lower()
    reason = getattr(error, "reason", None)
    if isinstance(reason, Exception):
        lowered = f"{lowered} {str(reason).lower()}"

    if "timed out" in lowered or "timeout" in lowered or name == "timeout":
        return (
            f"timed out after {spec.timeout}s reaching {spec.endpoint}. Raise "
            f"SALESPILOT_LLM_TIMEOUT, or the endpoint is not responding."
        )
    if (
        "getaddrinfo" in lowered
        or "name or service" in lowered
        or "nodename" in lowered
        or "no such host" in lowered
    ):
        return (
            f"the host in {spec.endpoint} does not resolve. Check "
            f"SALESPILOT_LLM_BASE_URL for a typo. [{name}: {text[:120]}]"
        )
    if "refused" in lowered:
        return (
            f"connection refused by {spec.endpoint}. Nothing is listening there. "
            f"[{name}: {text[:120]}]"
        )
    if "certificate" in lowered or "ssl" in lowered:
        return (
            f"TLS failed against {spec.endpoint}. [{name}: {text[:120]}]"
        )
    return f"cannot reach {spec.endpoint}. [{name}: {text[:160]}]"
