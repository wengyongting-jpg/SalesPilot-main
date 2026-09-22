# -*- coding: utf-8 -*-
"""Configuration: paths, model provider settings, thresholds and feature flags.

Read from the environment with conservative defaults, so the backend starts and
runs a full conversation with nothing configured at all. That property is
deliberate: a demo must not depend on a network.

Every flag that changes observable behaviour is reported by `--probe` and at
startup, because a silently different configuration is the failure mode this
rebuild exists to eliminate.
"""
from __future__ import annotations

import os
from decimal import Decimal, InvalidOperation
from pathlib import Path

# ---- Paths ---------------------------------------------------------------

PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_DIR.parent

# ---- Local configuration file --------------------------------------------

ENV_FILE = REPO_ROOT / ".env"


def load_env_file(path: Path = ENV_FILE) -> list[str]:
    """Read `.env` into the environment. Returns the names it set.

    Hand-rolled rather than adding `python-dotenv`: it is twenty lines, and the
    backend's dependency list is short enough to be worth keeping that way.

    **A real environment variable always wins.** The file is a convenience for local
    work, so `SALESPILOT_LLM_API_KEY=... ; py -3 -m backend --serve` must not be
    silently overridden by a stale line in a file somebody forgot about.
    """
    if not path.exists():
        return []

    applied: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        name = name.strip()
        value = value.strip()
        # Strip one layer of matching quotes, so a value with spaces can be quoted
        # without the quotes becoming part of it.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if not name or name in os.environ:
            continue
        os.environ[name] = value
        applied.append(name)
    return applied


ENV_FILE_APPLIED = load_env_file()

# Backend-owned data ships inside the package.
DATA_DIR = PACKAGE_DIR / "knowledge" / "data"
KB_PATH = DATA_DIR / "knowledge_base.json"

# Generated at runtime, so these live outside the package.
RUNTIME_DIR = REPO_ROOT / "runtime"
LOG_DIR = REPO_ROOT / "logs"
LOG_FILE = LOG_DIR / "backend.log"
DEFAULT_DB_PATH = RUNTIME_DIR / "backend.db"


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def _flag(name: str, *, default: bool) -> bool:
    """Parse a boolean environment flag. Unset means the default."""
    raw = _env(name).lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


# ---- Model provider ------------------------------------------------------
# SALESPILOT_LLM = offline (default) | openai | gateway
#
# `offline` is a real mode, not a broken one: rule-based extraction and template
# replies, with every message marked generation="template" so nobody mistakes it
# for model output.
LLM_PROVIDER = _env("SALESPILOT_LLM", "offline").lower()
LLM_MODEL = _env("SALESPILOT_LLM_MODEL", "gpt-4o-mini")
LLM_API_BASE = _env("SALESPILOT_LLM_BASE_URL") or None
LLM_API_KEY = (
    _env("SALESPILOT_LLM_API_KEY")
    or _env("OPENAI_API_KEY")
    or _env("HACKATHON_LLM_API_KEY")
) or None

# The organiser-provided gateway, when present, wins over a plain base URL.
HACKATHON_GATEWAY_URL = _env("HACKATHON_LLM_GATEWAY_URL") or None
if HACKATHON_GATEWAY_URL:
    LLM_API_BASE = HACKATHON_GATEWAY_URL

LLM_TIMEOUT_SECONDS = float(_env("SALESPILOT_LLM_TIMEOUT", "30"))
LLM_MAX_TOOL_STEPS = int(_env("SALESPILOT_LLM_MAX_TOOL_STEPS", "3"))
LLM_REQUEST_LIMIT = int(_env("SALESPILOT_LLM_REQUEST_LIMIT", "5"))
LLM_TOTAL_TOKEN_LIMIT = int(_env("SALESPILOT_LLM_TOTAL_TOKEN_LIMIT", "12000"))
LLM_OUTPUT_TOKEN_LIMIT = int(_env("SALESPILOT_LLM_OUTPUT_TOKEN_LIMIT", "2500"))
LLM_PER_REQUEST_INPUT_TOKEN_LIMIT = int(
    _env("SALESPILOT_LLM_PER_REQUEST_INPUT_TOKEN_LIMIT", "6000")
)


def _decimal_env(name: str, default: str) -> Decimal:
    try:
        value = Decimal(_env(name, default))
    except InvalidOperation as error:
        raise ValueError(f"{name} must be a decimal number") from error
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value


LLM_COST_LIMIT_USD = _decimal_env("SALESPILOT_LLM_COST_LIMIT_USD", "0.03")

# ---- Observability -------------------------------------------------------
# Prompts and raw model output are recorded and returned on the admin tier.
# Default ON: the point of this project is to show what the agent actually did,
# and a hidden prompt cannot be reviewed. It may contain the customer's own
# words, which is why the flag exists — turn it off for anything resembling
# production. Never exposed on the customer tier under any setting.
TELEMETRY_CONTENT = _flag("SALESPILOT_TELEMETRY_CONTENT", default=True)
TELEMETRY_CONTENT_MAX_CHARS = int(_env("SALESPILOT_TELEMETRY_CONTENT_MAX", "8000"))

# Per-run terminal rendering. Off in test runs, on when serving.
CONSOLE_TRACE = _flag("SALESPILOT_CONSOLE_TRACE", default=True)
CONSOLE_COLOUR = _flag("SALESPILOT_CONSOLE_COLOUR", default=True)

LOG_LEVEL = _env("SALESPILOT_LOG_LEVEL", "INFO").upper()

# ---- Scoring and escalation thresholds -----------------------------------
# Opportunity Value Score priority bands (100-point model).
HIGH_PRIORITY_MIN = 80
MEDIUM_PRIORITY_MIN = 50

# Below this retrieval confidence a specific product question is escalated
# rather than answered from a weak match.
RETRIEVAL_CONFIDENCE_ESCALATE = 0.5

# ---- HTTP ----------------------------------------------------------------

API_HOST = _env("SALESPILOT_HOST", "127.0.0.1")
API_PORT = int(_env("SALESPILOT_PORT", "8000"))

# Browser origins permitted to call the API. The two frontends are served as static
# files from a different port, so they are always cross-origin; without this a browser
# refuses every request before it reaches the backend.
#
# Loopback development origins only, and deliberately **not** `["*"]`. Nothing here is
# protected today — there is no authentication anywhere, which is a recorded demo
# limitation — but a wildcard sets a habit that becomes a real hole the moment auth
# exists. `allow_credentials` stays off for the same reason: there are no cookies or
# sessions to send, so permitting them would widen the surface for no benefit.
CORS_ORIGINS = [
    origin.strip()
    for origin in _env(
        "SALESPILOT_CORS_ORIGINS",
        "http://127.0.0.1:8123,http://localhost:8123,"
        "http://127.0.0.1:5500,http://localhost:5500",
    ).split(",")
    if origin.strip()
]

# ---- Compliance ----------------------------------------------------------
# Appended verbatim whenever a reply quotes a premium. Never truncated, never
# hidden: `.kiro/steering/product.md` treats this as a red line.
DEMO_DISCLAIMER = (
    "All premiums are fictional indicative rates for the SalesPilot demo and do "
    "not represent actual insurance quotations. Final premiums are subject to age, "
    "underwriting, plan selection and insurer assessment."
)


def redact(secret: str | None) -> str:
    """Describe a secret without revealing it.

    Shows only whether it exists and its length. Even a short suffix is avoidable
    credential material in shared logs and screen recordings.
    """
    if not secret:
        return "absent"
    return f"set ({len(secret)} chars)"


def describe() -> dict[str, object]:
    """A configuration summary safe to print at startup and to log.

    Secrets are reported by shape, never by value.
    """
    return {
        "env file": (
            f"{ENV_FILE.name} ({len(ENV_FILE_APPLIED)} settings)"
            if ENV_FILE_APPLIED
            else ("present, nothing applied" if ENV_FILE.exists() else "not present")
        ),
        "provider": LLM_PROVIDER,
        "model": LLM_MODEL,
        "api_base": LLM_API_BASE or "(provider default)",
        "api_key": redact(LLM_API_KEY),
        "telemetry_content": "on" if TELEMETRY_CONTENT else "off",
        "console_trace": "on" if CONSOLE_TRACE else "off",
        "model_limits": (
            f"tools={LLM_MAX_TOOL_STEPS}, requests={LLM_REQUEST_LIMIT}, "
            f"tokens={LLM_TOTAL_TOKEN_LIMIT}, output={LLM_OUTPUT_TOKEN_LIMIT}, "
            f"cost=${LLM_COST_LIMIT_USD} per segment"
        ),
        "knowledge_base": str(KB_PATH),
        "database": str(DEFAULT_DB_PATH),
    }


def model_configured() -> bool:
    """Whether a model call could even be attempted.

    A provider name alone is not enough: `SALESPILOT_LLM=gateway` with no key would
    otherwise produce a failure on every message instead of running the offline path.
    """
    return LLM_PROVIDER not in ("offline", "", "stub") and bool(LLM_API_KEY)
