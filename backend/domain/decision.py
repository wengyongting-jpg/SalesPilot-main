# -*- coding: utf-8 -*-
"""The kernel's recommendation, as plain data.

`NextBestAction` lives in `domain` rather than in `kernel` because two layers need
to read it and neither may import the other: `kernel` produces it, and `agent`
consumes `reply_mode` to decide how to pitch the reply.

The split inside it matters. `action` and `reason` are written for a **sales
representative** and belong to the admin tier only. `reply_mode` is the single field
the customer-facing path may act on, and it carries no internal vocabulary — see
`domain.enums.ReplyMode` for why that separation exists.
"""
from __future__ import annotations

from dataclasses import dataclass

from .enums import Priority, ReplyMode


@dataclass
class NextBestAction:
    action: str
    reason: str
    priority: Priority
    reply_mode: ReplyMode = ReplyMode.ANSWER
    human_intervention_required: bool = False
