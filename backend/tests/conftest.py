# -*- coding: utf-8 -*-
"""Pytest configuration for the rebuild's test suite.

The repository is run from source without installation, so the repository root
has to be importable before `import backend` works.
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
