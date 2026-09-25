# -*- coding: utf-8 -*-
"""Read-only staff availability from an approved weekly schedule.

No schedule means unknown, not an invented office-hours promise. All displayed
times are in Singapore time. This does not estimate queue response time.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from .. import config

# Singapore has no daylight-saving transition; a fixed UTC+08:00 offset also
# works on Windows hosts that do not ship the IANA timezone database.
SINGAPORE = timezone(timedelta(hours=8), "SGT")


def current_availability(now: datetime | None = None) -> dict:
    raw = config.STAFF_HOURS_JSON
    if not raw:
        return {"configured": False, "open": None, "next_open": None}
    schedule = json.loads(raw)
    if not isinstance(schedule, dict):
        raise ValueError("SALESPILOT_STAFF_HOURS_JSON must be an object")
    moment = now or datetime.now(SINGAPORE)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=SINGAPORE)
    local = moment.astimezone(SINGAPORE)
    closed_dates = config.STAFF_CLOSED_DATES
    for offset in range(8):
        day = (local + timedelta(days=offset)).date()
        if day.isoformat() in closed_dates:
            continue
        windows = schedule.get(str(day.weekday()), [])
        for start, end in windows:
            start_at = datetime.fromisoformat(f"{day.isoformat()}T{start}").replace(
                tzinfo=SINGAPORE
            )
            end_at = datetime.fromisoformat(f"{day.isoformat()}T{end}").replace(
                tzinfo=SINGAPORE
            )
            if end_at <= start_at:
                raise ValueError("Staff hours must end after they start")
            if start_at <= local < end_at:
                return {"configured": True, "open": True, "next_open": None}
            if start_at > local:
                return {
                    "configured": True,
                    "open": False,
                    "next_open": start_at.isoformat(),
                }
    return {"configured": True, "open": False, "next_open": None}


def customer_note(now: datetime | None = None) -> str:
    state = current_availability(now)
    if not state["configured"]:
        return "I don't have verified representative hours to share yet."
    if state["open"]:
        return "The representative team is currently within its scheduled hours."
    if state["next_open"]:
        opening = datetime.fromisoformat(state["next_open"])
        return (
            "The representative team is currently outside scheduled hours. "
            f"It next opens {opening.strftime('%A %d %B at %I:%M %p')} "
            "Singapore time. I can help with general plan information meanwhile."
        )
    return (
        "The representative team is currently outside scheduled hours. "
        "I can help with general plan information meanwhile."
    )
