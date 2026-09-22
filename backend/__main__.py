# -*- coding: utf-8 -*-
"""Allow `py -3 -m backend ...` from the repository root.

    py -3 -m backend --probe            report what model access is configured
    py -3 -m backend --serve --seed     start the API with demo data
    py -3 -m backend --demo             scripted demo, no server
"""
import sys

from .cli import main

if __name__ == "__main__":
    # Windows consoles default to a code page that mangles the box-drawing and
    # arrow characters used by the run renderer.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv[1:]))
