# -*- coding: utf-8 -*-
"""A read-only summary of the conversation so far.

Deliberately thin, and deliberately **free of sales intelligence**. The model is
composing a message the customer will read, so telling it the opportunity's state,
score or priority creates the leak that `docs/v0.0/backend/backend-plan.md` §3 red line 3 exists
to prevent. What it gets is what a colleague would tell it in a corridor: who this
is, which plan they have been discussing, and what they last said.

This is also the tier boundary applied to a tool return rather than to a response
body — the same rule, one layer further in.
"""
from __future__ import annotations

from ...domain.enums import MessageRole, Product
from . import ToolContext

_RECENT_TURNS = 6


def conversation_summary(context: ToolContext) -> str:
    """Who the customer is and what has been discussed, with nothing internal."""
    opp = context.opportunity
    if opp is None:
        result = "No earlier conversation with this customer."
    else:
        product = (
            context.kb.name(opp.product)
            if opp.product is not Product.UNKNOWN
            else "no specific plan yet"
        )
        lines = [
            f"Customer: {opp.customer_name}.",
            f"Plan under discussion: {product}.",
            f"Messages from the customer so far: {opp.customer_message_count}.",
        ]
        recent = [
            message for message in opp.messages
            if message.role is MessageRole.CUSTOMER
        ][-_RECENT_TURNS:]
        if recent:
            lines.append("Their most recent messages:")
            lines.extend(f"- {message.text}" for message in recent)
        result = "\n".join(lines)
    return context.record("conversation_summary", {}, result)
