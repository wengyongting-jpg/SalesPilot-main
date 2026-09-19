# -*- coding: utf-8 -*-
"""SalesPilot - CareSure's AI sales assistant (minimal runnable scaffold).

Module layout mirrors the Implementation Mapping from the project spec:
- knowledge:  knowledge-base loading and retrieval (future RAG / vector DB swap)
- detection:  intent, product and sales-signal detection (future LLM/model swap)
- engine:     opportunity state machine, value scoring, HITL escalation, next action
- response:   reply generation grounded in retrieved facts
- storage:    opportunity and human-case repository (future database swap)
- agent:      orchestrates the end-to-end Agent Workflow
"""

import sys as _sys

# SalesPilot uses modern type syntax (e.g. `str | None`) that only exists on
# Python 3.10+. On Python 3.9 or older this would otherwise fail with an
# obscure `TypeError: unsupported operand type(s) for |: 'type' and 'NoneType'`
# deep inside an import. Fail fast here with a clear, actionable message.
MIN_PYTHON = (3, 10)
if _sys.version_info < MIN_PYTHON:  # pragma: no cover - exercised via subprocess
    _current = ".".join(str(part) for part in _sys.version_info[:3])
    _required = ".".join(str(part) for part in MIN_PYTHON)
    raise RuntimeError(
        f"SalesPilot requires Python {_required} or newer, but you are running "
        f"Python {_current}. Please run it with a newer interpreter, e.g. "
        f"`python3.11 run.py` (or install Python {_required}+ and try again)."
    )

__version__ = "0.1.0"
