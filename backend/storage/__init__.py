# -*- coding: utf-8 -*-
"""Repositories: in-memory and SQLite.

Persists opportunities, human cases, idempotency receipts and agent runs. Only
`backend.services` writes through these.
"""
from __future__ import annotations

from pathlib import Path
from typing import Union

from .base import Repository
from .memory import MemoryRepository
from .sqlite import SqliteRepository


def open_repository(path: Union[str, Path, None] = None, *, memory: bool = False) -> Repository:
    """`memory=True` for a throwaway store; otherwise SQLite at `path` (default: config)."""
    if memory:
        return MemoryRepository()
    return SqliteRepository(path)


__all__ = ["MemoryRepository", "Repository", "SqliteRepository", "open_repository"]
