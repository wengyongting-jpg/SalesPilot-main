# -*- coding: utf-8 -*-
"""HTTP service layer (FastAPI). Importing the package does not require FastAPI;
the dependency is only needed when create_app() is actually called."""
from .app import create_app

__all__ = ["create_app"]
