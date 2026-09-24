# -*- coding: utf-8 -*-
"""Ordered, idempotent schema migrations.

Version 1 is `schema.sql`. Later versions append `(version, sql)` pairs to
`MIGRATIONS`; `apply` runs the ones the database has not recorded yet. The
frozen build patched columns ad hoc with `PRAGMA table_info` checks at every
startup; a recorded version is how a stored database says what it is.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

_SCHEMA_PATH = Path(__file__).with_name("schema.sql")

MIGRATIONS: list[tuple[int, str]] = [
    (1, _SCHEMA_PATH.read_text(encoding="utf-8")),
]


def apply(connection: sqlite3.Connection) -> int:
    """Bring `connection` up to the latest version; return that version."""
    connection.execute(
        "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    applied = {row[0] for row in connection.execute("SELECT version FROM schema_version")}
    for version, sql in MIGRATIONS:
        if version in applied:
            continue
        connection.executescript(sql)
        connection.execute(
            "INSERT OR IGNORE INTO schema_version (version, applied_at) VALUES (?, ?)",
            (version, datetime.now().isoformat()),
        )
    connection.commit()
    return MIGRATIONS[-1][0]
