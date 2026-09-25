# -*- coding: utf-8 -*-
"""Approved, channel-neutral, non-sensitive question catalogue."""
from __future__ import annotations

CATALOG = {
    "contact_reason": {
        "prompt": "What would you like help with?",
        "options": ["Compare plans", "Indicative price", "Apply", "Something else"],
    },
    "cover_type": {
        "prompt": "Who would need cover?",
        "options": ["Just me", "My family", "Employees", "Something else"],
    },
    "followup_time": {
        "prompt": "When would you prefer a follow-up?",
        "options": ["Morning", "Afternoon", "Evening", "Something else"],
    },
    "employee_count": {
        "prompt": "About how many employees would need cover?",
        "options": ["1-10", "11-50", "51-200", "201-500", "More than 500"],
    },
}


def payload(field: str | None) -> dict | None:
    if field not in CATALOG:
        return None
    item = CATALOG[field]
    return {
        "field": field,
        "prompt": item["prompt"],
        "options": [
            {"id": str(index), "label": label}
            for index, label in enumerate(item["options"], 1)
        ],
        "allow_other": True,
    }


def text_prompt(field: str) -> str:
    item = CATALOG[field]
    choices = " ".join(
        f"{index}. {label}" for index, label in enumerate(item["options"], 1)
    )
    return f"{item['prompt']} {choices}. Reply with a number or your own words."


def normalise_answer(field: str, text: str) -> str | None:
    if field not in CATALOG:
        return None
    cleaned = " ".join(text.split())[:200]
    if not cleaned:
        return None
    choices = CATALOG[field]["options"]
    if cleaned.isdigit() and 1 <= int(cleaned) <= len(choices):
        selected = choices[int(cleaned) - 1]
        return None if selected == "Something else" else selected
    for label in choices:
        if cleaned.casefold() == label.casefold():
            return None if label == "Something else" else label
    return cleaned
