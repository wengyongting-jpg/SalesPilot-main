# -*- coding: utf-8 -*-
"""Read-only conversation context: what has been said so far.

Deliberately built only from message text, never from kernel-derived fields
(state, score, signals). `agent` cannot import `kernel` anyway, but the
stronger reason is that a summary fed back into the model's own context is a
second place red line 3 (`docs/backend-plan.md` §3) could be broken if it
carried internal vocabulary — so it never has the chance to.
"""
from __future__ import annotations

from ...domain.message import Message

_MAX_SUMMARY_MESSAGES = 6


def get_conversation_summary(history: list[Message]) -> str:
    """A plain-text recap of the last few turns, for the model's own context."""
    if not history:
        return "No prior messages in this conversation."
    recent = history[-_MAX_SUMMARY_MESSAGES:]
    lines = []
    for msg in recent:
        speaker = "Customer" if msg.is_from_customer else "Business"
        lines.append(f"{speaker}: {msg.text}")
    return "\n".join(lines)
