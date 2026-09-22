# -*- coding: utf-8 -*-
"""The qualification gate: is this conversation a sales opportunity at all?

Specification: `docs/backend-contract.md` gap register item 13.

The previous build had no such question. Every conversation was scored as though it
were a customer, so advertising traffic was scored as though it were buying — spam
that borrowed insurance vocabulary reached 96 points and outranked a genuine
customer at 82, and the assistant replied "Great to hear you're interested!" to it.

The design principle here is not "judge accurately". The judgement originates in a
model and will sometimes be wrong, so instead the **cost of being wrong is made
small and reversible**:

    the machine may raise a conversation to HELD, and nothing further
    only a human may DISQUALIFY
    a hold is released by a human action, never by the machine

A false hold therefore costs the customer a cooler reply and costs a representative
one click. It never loses the lead, never deletes anything, and never sends a wrong
message. That asymmetry does more for safety than any amount of tuning could.

Two strikes are required, for the same reason: a single misjudged message must not
remove a real customer from the queue.
"""
from __future__ import annotations

from ..domain.detection import Detection
from ..domain.enums import Qualification
from ..domain.opportunity import Opportunity, QualificationVerdict

# A hold needs this many soliciting messages, unless one message is blatant.
_STRIKES_REQUIRED = 2

_HOLD_REASON = (
    "Held pending review: the conversation appears to be promoting something rather "
    "than enquiring about cover"
)


def assess(opp: Opportunity, det: Detection) -> QualificationVerdict:
    """Decide the qualification level for this turn.

    Pure: reads the profile and this turn's observations, returns a verdict. The
    caller applies it. Never returns DISQUALIFIED unless it was already set by a
    human.
    """
    # A human decision is final. The machine neither escalates past it nor
    # overturns it.
    if opp.qualification is Qualification.DISQUALIFIED:
        return QualificationVerdict(
            level=Qualification.DISQUALIFIED,
            reason=opp.qualification_reason or "Disqualified by a representative",
            evidence=["set by a human; the machine does not revisit it"],
        )

    # A hold persists until a human releases it. Otherwise a spammer clears its own
    # hold by sending one polite sentence.
    if opp.qualification is Qualification.HELD:
        return QualificationVerdict(
            level=Qualification.HELD,
            reason=opp.qualification_reason or _HOLD_REASON,
            evidence=["already held; release is a human action"],
        )

    evidence: list[str] = []

    # Blatant case: the semantic judgement and the deterministic marker agree on
    # the same message. One strike is enough, because two independent observations
    # already concur.
    if det.solicitation and not det.genuine_enquiry:
        evidence.append("this message solicits rather than enquires")
        evidence.append("not assessed as a genuine enquiry")
        return QualificationVerdict(
            level=Qualification.HELD, reason=_HOLD_REASON, evidence=evidence
        )

    # Accumulated case: two soliciting messages in the same conversation.
    strikes = opp.solicitation_count + (1 if det.solicitation else 0)
    if det.solicitation and strikes >= _STRIKES_REQUIRED:
        evidence.append(f"{strikes} messages in this conversation solicit rather than enquire")
        return QualificationVerdict(
            level=Qualification.HELD, reason=_HOLD_REASON, evidence=evidence
        )

    if det.solicitation:
        evidence.append(
            f"{strikes} of {_STRIKES_REQUIRED} soliciting messages — not yet held"
        )

    return QualificationVerdict(level=Qualification.QUALIFIED, evidence=evidence)


def disqualify(opp: Opportunity, *, reason: str) -> QualificationVerdict:
    """Record a representative's decision to disqualify.

    Exposed as a distinct function rather than a level `assess` can return, so that
    "only a human disqualifies" is visible in the call graph rather than being a
    comment somebody can overlook.
    """
    return QualificationVerdict(
        level=Qualification.DISQUALIFIED,
        reason=reason,
        evidence=["set by a representative"],
    )


def release(opp: Opportunity, *, reason: str = "Released by a representative") -> QualificationVerdict:
    """Return a held or disqualified conversation to the sales queue."""
    return QualificationVerdict(
        level=Qualification.QUALIFIED,
        reason=reason,
        evidence=["released by a representative"],
    )
