# -*- coding: utf-8 -*-
"""Scripted demo: the Sarah / Michael / ABC Pte Ltd conversations from the spec."""
from .agent import SalesPilotAgent
from .dashboard import render_dashboard

# (customer_id, name, [messages])
SCRIPT: list[tuple[str, str, list[str]]] = [
    (
        "C-1024",
        "Sarah",
        [
            "Hi! I'm looking for health insurance with private hospital coverage.",
            "How much does CareSure Plus cost?",
            "Can I add my child to the plan?",
            "It's a bit expensive, and another insurer offered something cheaper.",
            "How do I apply? What documents do I need?",
        ],
    ),
    (
        "C-1025",
        "Michael",
        [
            "Hi, what's your cheapest basic plan?",
            "Thanks. What does the Essential plan cover?",
        ],
    ),
    (
        "C-1026",
        "ABC Pte Ltd",
        [
            "We are a company with 120 employees and need corporate health "
            "insurance for our staff.",
            "We'd like to proceed with a corporate quotation. How do we sign up?",
        ],
    ),
]


def run_demo(agent: SalesPilotAgent) -> str:
    for customer_id, name, messages in SCRIPT:
        print("=" * 74)
        print(f"Conversation with {name} ({customer_id}) - simulated WhatsApp")
        print("=" * 74)
        result = None
        for text in messages:
            print(f"\nCustomer > {text}")
            result = agent.handle_message(customer_id, name, text)
            print(f"SalesPilot > {result.reply}")
            print(
                f"   [state] {result.state_change} | "
                f"[signals] {', '.join(s.value for s in result.detection.signals) or '-'} | "
                f"[score] {result.score.total}/100 {result.score.priority.value}"
            )
            if result.case:
                print(f"   [HITL] Case {result.case.id} opened: {result.case.reason}")
        print()

    dashboard = render_dashboard(agent.repo)
    print(dashboard)
    return dashboard
