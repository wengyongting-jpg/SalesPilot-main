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

import json

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


def search_conversation_history(
    context: ToolContext, query: str, limit: int = 3
) -> str:
    """Find a few older messages in the current opportunity, with source IDs."""
    query = " ".join(str(query).split())[:120]
    bounded_limit = max(1, min(int(limit), 5))
    if not query:
        return context.record("search_conversation_history", {"query": "", "limit": bounded_limit}, "[]")
    if context.history_search is None:
        context.history_errors.append("history lookup is unavailable")
        result = "History lookup is unavailable for this run."
    else:
        try:
            matches = context.history_search(query, bounded_limit)
            # Keep each result small even if a stored message is unusually long.
            compact = [
                {**item, "text": str(item.get("text", ""))[:320]}
                for item in matches[:bounded_limit]
            ]
            result = json.dumps(compact, ensure_ascii=False)
        except Exception as error:
            context.history_errors.append(f"history lookup failed ({type(error).__name__})")
            result = "History lookup failed; no message content was returned."
    return context.record(
        "search_conversation_history", {"query": query, "limit": bounded_limit}, result
    )
