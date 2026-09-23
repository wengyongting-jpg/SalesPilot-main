# -*- coding: utf-8 -*-
"""Model-facing proposal for backend-approved customer questions."""
from __future__ import annotations

from ...knowledge.questions import CATALOG
from . import ToolContext


def propose_customer_question(context: ToolContext, field: str) -> str:
    """Propose one approved missing field; this does not message the customer."""
    if field not in CATALOG:
        return context.record(
            "propose_customer_question", {"field": field},
            f"Rejected. Allowed fields: {', '.join(CATALOG)}",
        )
    if context.opportunity and field in context.opportunity.collected_answers:
        return context.record(
            "propose_customer_question", {"field": field},
            "Already known. Do not ask again.",
        )
    context.question_field = field
    return context.record(
        "propose_customer_question", {"field": field},
        f"Proposed {field}; the backend will decide whether to ask it.",
    )
