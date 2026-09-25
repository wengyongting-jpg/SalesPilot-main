# -*- coding: utf-8 -*-
"""Compatibility entry point for the current backend.

Prefer ``python -m backend``. The accepted options are those of
``backend.cli``; legacy interactive and semantic options are no longer present.
"""
import sys

# --- Python version guard ------------------------------------------------
# SalesPilot uses `X | None` type syntax which requires Python 3.10+. Give a
# friendly message here instead of a confusing TypeError from deep inside an
# import. This check uses only Python 2/3-safe syntax so even very old
# interpreters reach the message.
_MIN_PYTHON = (3, 10)
if sys.version_info < _MIN_PYTHON:
    _current = ".".join(str(p) for p in sys.version_info[:3])
    sys.stderr.write(
        "SalesPilot requires Python 3.10 or newer, but you are running "
        "Python " + _current + ".\n"
        "Please start it with a newer interpreter, for example:\n"
        "    python3.11 run.py\n"
    )
    raise SystemExit(1)

from backend.cli import main  # noqa: E402

if __name__ == "__main__":
    # UTF-8 fallback for Windows consoles
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv[1:]))
