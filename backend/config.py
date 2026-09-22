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
from pathlib import Path

# ---- Paths ---------------------------------------------------------------

PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_DIR.parent

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
LLM_MAX_TOOL_STEPS = int(_env("SALESPILOT_LLM_MAX_TOOL_STEPS", "6"))

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

# ---- Compliance ----------------------------------------------------------
# Appended verbatim whenever a reply quotes a premium. Never truncated, never
# hidden: `.kiro/steering/product.md` treats this as a red line.
DEMO_DISCLAIMER = (
    "All premiums are fictional indicative rates for the SalesPilot demo and do "
    "not represent actual insurance quotations. Final premiums are subject to age, "
    "underwriting, plan selection and insurer assessment."
)


def describe() -> dict[str, object]:
    """A configuration summary safe to print at startup and to log.

    Secrets are reported as presence, never as value.
    """
    return {
        "provider": LLM_PROVIDER,
        "model": LLM_MODEL,
        "api_base": LLM_API_BASE or "(provider default)",
        "api_key": "set" if LLM_API_KEY else "absent",
        "telemetry_content": "on" if TELEMETRY_CONTENT else "off",
        "console_trace": "on" if CONSOLE_TRACE else "off",
        "knowledge_base": str(KB_PATH),
        "database": str(DEFAULT_DB_PATH),
    }
