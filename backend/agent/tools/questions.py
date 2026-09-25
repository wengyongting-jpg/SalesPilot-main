# -*- coding: utf-8 -*-
"""Model-facing proposal for backend-approved customer questions."""
from __future__ import annotations

from ...knowledge.questions import CATALOG
from . import ToolContext


def propose_customer_question(context: ToolContext, field: str) -> str:
    """Propose one approved missing field; this does not message the customer.

    Propose only when the detail is genuinely missing and would change what
    you say next - never re-ask a field already recorded, and never propose
    one to delay an explicit human request.
    """
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


# Appended rather than hardcoded in the docstring above: the tool schema a
# model sees must list the *current* catalogue, not a copy that silently goes
# stale the next time a field is added or removed.
propose_customer_question.__doc__ += f"\n\n    Allowed field values: {', '.join(CATALOG)}."
