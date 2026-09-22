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


def compose(
    *,
    retrieval: RetrievalResult,
    withdrawal: bool = False,
    takeover: bool = False,
    escalate: bool = False,
    recorder: Optional[RunRecorder] = None,
) -> Message:
    """Compose a grounded reply and wrap it as a business `Message`."""
    if withdrawal:
        mode, text = "withdrawal", _WITHDRAWAL_MESSAGE
    elif takeover or escalate:
        mode, text = "takeover", _TAKEOVER_MESSAGE
    else:
        mode, text = "answer", _answer(retrieval)
    if recorder is not None:
        with recorder.step("response_generation", "rule") as step:
            step.note(f"template={mode} facts={len(retrieval.facts)}")
    return Message.from_ai(text, generation=Generation.TEMPLATE)


def _answer(retrieval: RetrievalResult) -> str:
    parts = ["Thanks for reaching out. Here is what I can share:"]
    parts.extend(f"- {fact}" for fact in retrieval.facts[:4])
    if any("premium" in fact.lower() for fact in retrieval.facts):
        parts.append(config.DEMO_DISCLAIMER)
    return "\n".join(parts)
