# -*- coding: utf-8 -*-
"""SalesPilot entry point.

Usage:
    py -3 run.py              # Interactive chat simulation (minimal WhatsApp mock)
    py -3 run.py --demo       # Run the scripted demo and print the sales dashboard
    py -3 run.py --seed --db runtime/salespilot.db
                              # Persist demo data into a SQLite database
    py -3 run.py --serve --seed
                              # Start the FastAPI service, seeding demo data first
    py -3 run.py --semantic   # Use the offline embedding/vector-store retriever
"""
import sys
from pathlib import Path

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

# Allow running directly from the project root (no `pip install -e .` needed)
sys.path.insert(0, str(Path(__file__).resolve().parent))

from salespilot.cli import main  # noqa: E402

if __name__ == "__main__":
    # UTF-8 fallback for Windows consoles
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv[1:]))
