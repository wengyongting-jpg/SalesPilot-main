# -*- coding: utf-8 -*-
"""The one tool that touches escalation — and only as a proposal.

`request_human_handoff` cannot open a case, move a state, or change a score.
It constructs a `HandoffProposal` and nothing else; `backend.kernel.hitl`
reads it as one input among several and decides for itself. Modelling the
handoff this way lets telemetry show that the model asked and the kernel
declined (`docs/backend-plan.md` §3).
"""
from __future__ import annotations

from ...domain.detection import HandoffProposal


def request_human_handoff(reason: str) -> HandoffProposal:
    """Propose that a person take over this conversation, and why."""
    return HandoffProposal(requested=True, reason=reason)
