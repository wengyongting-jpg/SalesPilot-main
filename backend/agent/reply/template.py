# -*- coding: utf-8 -*-
"""Deterministic reply composition: the offline peer of `reply.model_based`.

Grounded entirely in `RetrievalResult.facts` — never invents a product fact —
and marks its own output `generation="template"` so a reader is never misled
into thinking a model produced this wording. Ported from
`salespilot/response/generator.py`'s grounded-answer logic, simplified: mode
selection (nurture/follow-up/answer/withdrawal/takeover/escalation) is a
caller decision here, driven by the same primitive flags
`policy.customer_safe_projection` takes, rather than this module reaching
into kernel-derived `Opportunity`/`NextBestAction` objects it cannot import.
"""
from __future__ import annotations

from typing import Optional

from ... import config
from ...domain.detection import RetrievalResult
from ...domain.enums import Generation
from ...domain.message import Message
from ...observability import RunRecorder

_WITHDRAWAL_MESSAGE = (
    "Thanks for letting me know, and no problem at all. I completely respect "
    "your decision and won't push anything further. If your needs change in "
    "the future, I'm here whenever you'd like to pick things up again. "
    "Wishing you all the best."
)

_TAKEOVER_MESSAGE = (
    "Thanks for your message. A CareSure representative is now personally "
    "looking after your case and will follow up with you directly."
)

# The customer's first message, with nothing specific to answer yet (intent
# GENERIC). Ported from `salespilot/response/generator.py`'s `_GENERIC_HELP`,
# which this rebuild's template composer had dropped: without it, a bare "hi"
# fell through to `_answer`, and a message with no product and no preferred
# knowledge-base field retrieves the full four-plan overview — so a greeting
# was answered with a wall of unrelated premiums. Scoped to the first message
# only, matching the frozen build: a later "hi" mid-conversation is a customer
# question like any other and still gets `_answer`.
_GREETING_MESSAGE = (
    "Hi! I'm CareSure's AI assistant. I can help with plan information, "
    "indicative premiums, coverage, eligibility, claims and applications. "
    "Which plan would you like to know about: Essential, Family, Plus or "
    "Corporate?"
)


def compose(
    *,
    retrieval: RetrievalResult,
    withdrawal: bool = False,
    takeover: bool = False,
    escalate: bool = False,
    greeting: bool = False,
    recorder: Optional[RunRecorder] = None,
    degraded_reason: Optional[str] = None,
) -> Message:
    """Compose a grounded reply and wrap it as a business `Message`.

    `degraded_reason` marks the step degraded — set when this composer ran
    because no model was configured, not when a template is the right answer
    (a withdrawal or a handover is deterministic by design, at any provider).
    """
    if withdrawal:
        mode, text = "withdrawal", _WITHDRAWAL_MESSAGE
    elif takeover or escalate:
        mode, text = "takeover", _TAKEOVER_MESSAGE
    elif greeting:
        mode, text = "greeting", _GREETING_MESSAGE
    else:
        mode, text = "answer", _answer(retrieval)
    if recorder is not None:
        with recorder.step("response_generation", "rule") as step:
            if degraded_reason:
                step.degrade(degraded_reason)
            else:
                step.note(f"template={mode} facts={len(retrieval.facts)}")
    return Message.from_ai(text, generation=Generation.TEMPLATE)


def _answer(retrieval: RetrievalResult) -> str:
    parts = ["Thanks for reaching out. Here is what I can share:"]
    parts.extend(f"- {fact}" for fact in retrieval.facts[:4])
    if retrieval.mentions_premium:
        parts.append(config.DEMO_DISCLAIMER)
    return "\n".join(parts)
