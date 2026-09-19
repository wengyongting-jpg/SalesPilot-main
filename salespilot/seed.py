# -*- coding: utf-8 -*-
"""Seed the repository with the scripted demo conversations.

Running the seed produces the same data as `run.py --demo` but persists it
through whatever repository the agent uses (in-memory for tests, SQLite for the
API server), so dashboards and analytics have data to show.
"""
from __future__ import annotations

from .agent import SalesPilotAgent
from .demo import SCRIPT


def seed_demo_data(agent: SalesPilotAgent) -> dict:
    """Replay every demo conversation through the agent; return a summary."""
    customers = 0
    messages = 0
    for customer_id, name, texts in SCRIPT:
        customers += 1
        for text in texts:
            agent.handle_message(customer_id, name, text)
            messages += 1
    return {
        "customers_seeded": customers,
        "messages_seeded": messages,
        "opportunities": len(agent.repo.list_opportunities()),
        "human_cases": len(agent.repo.list_cases()),
    }
