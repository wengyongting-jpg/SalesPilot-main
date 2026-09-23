# -*- coding: utf-8 -*-
"""Demo data: three scripted customers, replayed through the real pipeline.

Seeding is idempotent at the repository level — a store that already holds
opportunities is left alone — so `POST /api/seed` (P6) and `--seed` can be
called freely. The script is the frozen build's (`salespilot/demo.py`), kept
verbatim so the two builds can be compared on identical input.
"""
from __future__ import annotations

from ..domain.enums import Priority
from ..storage.base import Repository
from .conversation import ConversationService

SCRIPT: list[tuple[str, str, list[str]]] = [
    ("C-1024", "Sarah", [
        "Hi! I'm looking for health insurance with private hospital coverage.",
        "How much does CareSure Plus cost?",
        "Can I add my child to the plan?",
        "It's a bit expensive, and another insurer offered something cheaper.",
        "How do I apply? What documents do I need?",
    ]),
    ("C-1025", "Michael", [
        "Hi, what's your cheapest basic plan?",
        "Thanks. What does the Essential plan cover?",
    ]),
    ("C-1026", "ABC Pte Ltd", [
        "We are a company with 120 employees and need corporate health insurance for our staff.",
        "We'd like to proceed with a corporate quotation. How do we sign up?",
    ]),
]


def seed(service: ConversationService) -> dict:
    repo = service.repo
    if repo.list_opportunities():
        return {"seeded": False, "reason": "repository already contains opportunities"}
    messages = 0
    for customer_id, name, texts in SCRIPT:
        for index, text in enumerate(texts):
            service.handle_customer_message(
                customer_id, name, text, client_message_id=f"seed-{customer_id}-{index}"
            )
            messages += 1
    return {
        "seeded": True,
        "customers_seeded": len(SCRIPT),
        "messages_seeded": messages,
        "opportunities": len(repo.list_opportunities()),
        "human_cases": len(repo.list_cases()),
    }


def render_summary(repo: Repository) -> str:
    """The terminal dashboard, ported from `salespilot/dashboard.py`."""
    opps = repo.list_opportunities()
    counts = {p: 0 for p in Priority}
    for opp in opps:
        counts[opp.priority or Priority.LOW] += 1

    width = 78
    lines = [
        "=" * width,
        "SALES DASHBOARD - CareSure SalesPilot",
        "=" * width,
        f"  [ HIGH {counts[Priority.HIGH]} ]   [ MEDIUM {counts[Priority.MEDIUM]} ]   [ LOW {counts[Priority.LOW]} ]",
        "-" * width,
        f"{'Customer':<16}{'State':<26}{'Product':<11}{'Score':>6}  {'Qual':<10}{'Action'}",
        "-" * width,
    ]
    order = {Priority.HIGH: 0, Priority.MEDIUM: 1, Priority.LOW: 2}
    for opp in sorted(opps, key=lambda o: order[o.priority or Priority.LOW]):
        score = str(opp.score.total) if opp.score else "-"
        action = "Take Over" if opp.human_takeover else "Follow Up"
        signals = "+".join(s.value for s in opp.signals)
        lines.append(
            f"{opp.customer_name:<16}{opp.state.value:<26}{opp.product.value.title():<11}"
            f"{score:>6}  {opp.qualification.value:<10}{action}"
            + (f" [{signals}]" if signals else "")
        )

    cases = repo.list_cases()
    lines.append("-" * width)
    lines.append(f"HUMAN CASES (Open: {sum(1 for c in cases if c.status.value == 'Open')})")
    for case in cases:
        lines.append(f"  [{case.status.value}] {case.id} | {case.customer_name} | {case.reason}")
    lines.append("=" * width)
    return "\n".join(lines)
