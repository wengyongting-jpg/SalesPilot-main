# -*- coding: utf-8 -*-
"""Global configuration: paths, thresholds, provider settings and demo copy."""
import os
from pathlib import Path

# Paths
ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
KB_PATH = DATA_DIR / "knowledge_base.json"
LOG_DIR = ROOT_DIR / "logs"
LOG_FILE = LOG_DIR / "salespilot.log"
RUNTIME_DIR = ROOT_DIR / "runtime"
DEFAULT_DB_PATH = RUNTIME_DIR / "salespilot.db"

# ---- Pluggable AI providers ----------------------------------------------
# The engine itself stays provider-agnostic and works fully offline. These
# settings only matter when an LLM-backed generator / semantic retriever is
# wired in explicitly.
#   SALESPILOT_LLM=stub (default) | openai | gateway
# When SALESPILOT_LLM=gateway, uses the Hackathon-provided LLM Gateway URL.
LLM_PROVIDER = os.getenv("SALESPILOT_LLM", "stub").strip().lower()
LLM_MODEL = os.getenv("SALESPILOT_LLM_MODEL", "gpt-4o-mini").strip()
LLM_API_BASE = os.getenv("SALESPILOT_LLM_BASE_URL", "").strip() or None
LLM_API_KEY = (
    os.getenv("SALESPILOT_LLM_API_KEY")
    or os.getenv("OPENAI_API_KEY")
    or os.getenv("HACKATHON_LLM_API_KEY")
    or ""
).strip() or None

# Hackathon LLM Gateway (if provided, takes precedence over base URL)
HACKATHON_GATEWAY_URL = os.getenv("HACKATHON_LLM_GATEWAY_URL", "").strip() or None
if HACKATHON_GATEWAY_URL:
    LLM_API_BASE = HACKATHON_GATEWAY_URL

# Dimension of the offline hashing embedder used by the semantic retriever
LOCAL_EMBED_DIM = 512

# API server defaults
API_HOST = os.getenv("SALESPILOT_HOST", "127.0.0.1")
API_PORT = int(os.getenv("SALESPILOT_PORT", "8000"))

# Opportunity Value Score priority bands (spec: 80-100 High / 50-79 Medium / 0-49 Low)
HIGH_PRIORITY_MIN = 80
MEDIUM_PRIORITY_MIN = 50

# Retrieval confidence: below this a product-specific question is escalated
RETRIEVAL_CONFIDENCE_ESCALATE = 0.5

DEMO_DISCLAIMER = (
    "All premiums are fictional indicative rates for the SalesPilot demo and do "
    "not represent actual insurance quotations. Final premiums are subject to age, "
    "underwriting, plan selection and insurer assessment."
)
