# -*- coding: utf-8 -*-
"""Logger setup: one line per event, and the full run block when tracing is on.

Kept separate from `console` because the two answer different questions. The console
block is for somebody watching a demo and wanting to see what the agent just did. The
log is for somebody asking afterwards what happened at 14:32.
"""
from __future__ import annotations

import logging
import sys
from typing import Optional

from .. import config
from .console import ASCII, render
from .run import AgentRun, RunStatus

_LOGGER_NAME = "salespilot.backend"
_configured = False

# Map a run status onto a log level so a degradation is not filed as routine
# information. This is the point: in the previous build a silent fallback to the
# rule-based extractor produced no log line at all.
_LEVEL_FOR_STATUS = {
    RunStatus.OK: logging.INFO,
    RunStatus.DEGRADED: logging.WARNING,
    RunStatus.ERROR: logging.ERROR,
}


def _level_for(run: AgentRun) -> int:
    """The level this run deserves.

    One refinement on the status mapping: a run that degraded **only** because no model
    is configured is reported at INFO, not WARNING.

    Offline is the documented default, and every run in it degrades. Warning on each
    one costs twice: the default mode reads as broken, and a real warning — a provider
    timing out, a model returning a value the domain rejects — arrives in a stream of
    identical expected ones and is missed. Alarm fatigue is not a cosmetic problem; it
    is the same failure as no alarm at all, arrived at from the other direction.

    What does *not* change: the run still reports `status: "degraded"` on the wire and
    the reason is still recorded on the step. Nothing is hidden. Only the loudness
    moves, and only for the case that was expected.
    """
    if run.status is RunStatus.DEGRADED and run.degraded_by_design:
        return logging.INFO
    return _LEVEL_FOR_STATUS[run.status]


def get_logger() -> logging.Logger:
    global _configured
    logger = logging.getLogger(_LOGGER_NAME)
    if _configured:
        return logger

    logger.setLevel(getattr(logging, config.LOG_LEVEL, logging.INFO))
    logger.propagate = False

    stream = logging.StreamHandler(stream=sys.stdout)
    stream.setFormatter(logging.Formatter("%(levelname)-8s %(message)s"))
    logger.addHandler(stream)

    try:
        config.LOG_DIR.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(config.LOG_FILE, encoding="utf-8")
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-8s %(message)s")
        )
        logger.addHandler(file_handler)
    except OSError as error:
        # A read-only or missing log directory must not stop the service. Say so on
        # the stream handler that did attach, rather than failing silently.
        logger.warning("file logging unavailable (%s); logging to stdout only", error)

    _configured = True
    return logger


def log_run(run: AgentRun, *, trace: Optional[bool] = None) -> None:
    """Log one completed run.

    A summary line always; the full block when tracing is on. An unexpected degradation
    is logged at WARNING and an error at ERROR, so neither can hide inside routine
    output — while a degradation that is the configured mode goes to INFO, so it cannot
    bury the other two. See `_level_for`.
    """
    logger = get_logger()
    totals = run.totals()
    level = _level_for(run)
    logger.log(
        level,
        "run %s | %s | %s | %dms | %d llm, %d tool, %d tok, %s%s",
        run.run_id,
        run.opportunity_id,
        run.status.value,
        run.duration_ms,
        totals["llm_call_count"],
        totals["tool_call_count"],
        totals["total_tokens"],
        run.total_cost.describe(),
        f" | {len(run.violations)} violation(s)" if run.violations else "",
    )

    should_trace = config.CONSOLE_TRACE if trace is None else trace
    if should_trace:
        for line in render(run, glyphs=ASCII).splitlines():
            logger.log(level, line)
