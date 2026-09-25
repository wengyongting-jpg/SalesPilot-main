# -*- coding: utf-8 -*-
"""The one tool that is not a read: proposing a handover to a person.

It records a request and returns an acknowledgement. It does **not** open a case, set
a takeover flag, or change a state — `backend.kernel.hitl` reads the proposal as one
input among several and decides for itself, and there are triggers it fires on that
the model never sees.

The wording returned to the model matters. "Noted" is honest; anything resembling
"done" would teach it that asking is the same as receiving, and a model that believes
a handover is already arranged will tell the customer so.
"""
from __future__ import annotations

from . import ToolContext


def request_human_handoff(context: ToolContext, reason: str) -> str:
    """Ask for a human representative to take over, giving a reason.

    Call this when the customer asks for a person, or when answering would require a
    personalised medical, underwriting, claims or pricing decision.
    """
    cleaned = " ".join(str(reason).split())[:200]
    context.handoff.requested = True
    context.handoff.reason = cleaned
    result = (
        "Noted. Your request has been recorded for review; whether a representative "
        "takes over is decided separately, so do not promise the customer a handover."
    )
    return context.record("request_human_handoff", {"reason": cleaned}, result)
