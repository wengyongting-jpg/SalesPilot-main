# -*- coding: utf-8 -*-
"""Scripted demo conversations, replayed through the real pipeline.

Each seeded conversation is produced by actually sending its messages through
`ConversationService`, not by writing rows. That is slower and entirely the point: a
fixture built by inserting records can describe a state the pipeline cannot reach, and
a demo resting on one is a demo of the fixture.

Idempotent. Seeding twice adds nothing, because a demo operator will press the button
twice.
"""
from __future__ import annotations

from ..observability.logging import get_logger

# Four conversations: a competitive high-intent lead, a hesitant budget shopper, a
# corporate enquiry, and an advertiser — the last one so the qualification gate is
# visible in the queue rather than only in a test.
SCRIPTS: dict[str, dict] = {
    "C-1024": {
        "name": "Sarah",
        "messages": [
            "I want private hospital coverage for myself",
            "How much is the Plus plan?",
            "Another insurer is cheaper, and I have a child to cover too",
            "Okay, how do I apply?",
        ],
    },
    "C-1025": {
        "name": "Michael",
        "messages": [
            "What is your cheapest basic plan?",
            "That seems a little expensive for me",
            "Let me think about it",
        ],
    },
    "C-1026": {
        "name": "ABC Pte Ltd",
        "messages": [
            "We have 120 employees and need group coverage",
            "What does the corporate plan include?",
            "Can you send a quotation? I want to buy",
        ],
    },
    "C-9001": {
        "name": "Growth Partners",
        "messages": [
            "We sell insurance leads, visit example.com for our list",
            "Buy our database now, limited time offer with a promo code",
        ],
    },
}


def seed(conversation_service) -> dict:
    """Seed the demo data. Returns a summary; idempotent."""
    logger = get_logger()
    repo = conversation_service.repo

    if repo.list_opportunities():
        return {
            "seeded": False,
            "reason": "the repository already contains conversations",
            "customers_seeded": 0,
        }

    for customer_id, script in SCRIPTS.items():
        for text in script["messages"]:
            conversation_service.handle_customer_message(
                customer_id=customer_id,
                customer_name=script["name"],
                text=text,
            )

    logger.info("seeded %d demo conversations", len(SCRIPTS))
    return {
        "seeded": True,
        "customers_seeded": len(SCRIPTS),
        "conversations": list(SCRIPTS),
    }
