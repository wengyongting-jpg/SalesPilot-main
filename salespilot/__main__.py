# -*- coding: utf-8 -*-
"""Allow running via `py -3 -m salespilot`."""
import sys

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
