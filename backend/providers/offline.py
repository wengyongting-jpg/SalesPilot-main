# -*- coding: utf-8 -*-
"""The offline transport: no model, deterministic path only.

Not a broken stand-in. Selecting this on purpose (or falling back to it after
a failed probe) is a first-class, supported configuration — every message it
produces is marked `generation="template"`, never silently.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OfflineTransport:
    """A marker value: there is no model transport to construct."""

    reason: str = "offline provider configured"
