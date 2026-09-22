# -*- coding: utf-8 -*-
"""Structured logger setup: one JSON line per agent run.

Prompt and model output content never reach the log file — the file is the
long-lived, least-guarded copy, so it records lengths only, regardless of
`TELEMETRY_CONTENT`. Content lives on the admin tier (P6) and nowhere else.
"""
from __future__ import annotations

import json
import logging as _logging

from .. import config
from .run import AgentRun

_LOGGER_NAME = "salespilot.backend"


def configure() -> _logging.Logger:
    """Idempotent: safe to call from the CLI, the API and tests alike."""
    logger = _logging.getLogger(_LOGGER_NAME)
    if getattr(logger, "_salespilot_configured", False):
        return logger
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    handler = _logging.FileHandler(config.LOG_FILE, encoding="utf-8")
    handler.setFormatter(_logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(config.LOG_LEVEL)
    logger.propagate = False
    logger._salespilot_configured = True  # type: ignore[attr-defined]
    return logger


def log_run(run: AgentRun) -> None:
    logger = configure()
    payload = run.to_dict(include_content=False)
    level = _logging.WARNING if run.status != "ok" else _logging.INFO
    logger.log(level, "agent_run %s", json.dumps(payload, ensure_ascii=False, default=str))
