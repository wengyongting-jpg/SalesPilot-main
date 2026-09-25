# -*- coding: utf-8 -*-
"""Read-only representative availability for the observation agent."""
from __future__ import annotations

import json

from ...knowledge.availability import current_availability
from . import ToolContext


def get_staff_availability(context: ToolContext) -> str:
    """Return configured staff availability, never a guessed response-time SLA."""
    result = json.dumps(current_availability())
    return context.record("get_staff_availability", {}, result)
