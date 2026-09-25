# -*- coding: utf-8 -*-
"""Next best action: what a representative should do, and whether they are needed.

Derived from state, signals, score band and the risk flags. The assistant recommends
*sales* actions only — it never recommends an underwriting, claims or pricing
decision, and nothing here is an input to one.

Three gates run before the state rules, in this order, because each overrides
everything below it:

    withdrawn   the customer said no. Stop active follow-up. Continuing to
                recommend a push would be the system arguing with the customer.
    held        not a sales opportunity. No selling action, and no representative
                consumed either — the point of holding is to spend nobody's time.
    takeover    a person already owns it (P0-3). The AI does not resume autonomous
                selling on a later message merely because that message did not
                independently re-trigger escalation.
"""
from __future__ import annotations

from ..domain.decision import NextBestAction
from ..domain.detection import Detection
from ..domain.enums import (
    OpportunityState,
    Priority,
    Qualification,
    ReplyMode,
    Signal,
)

__all__ = ["NextBestAction", "recommend"]


def recommend(opp, det: Detection, *, escalated: bool = False) -> NextBestAction:
    signals = set(det.signals) | set(opp.signals)
    priority = opp.score.priority if opp.score else Priority.LOW

    # ---- Gates -----------------------------------------------------------

    if Signal.WITHDRAWAL in signals:
        return NextBestAction(
            action="Stop active sales follow-up — mark as Dormant/Lost",
            reason="The customer explicitly withdrew their purchase intent",
            priority=Priority.LOW,
            reply_mode=ReplyMode.WITHDRAWN,
            human_intervention_required=False,
        )

    if opp.qualification is not Qualification.QUALIFIED:
        return NextBestAction(
            action="No sales action — awaiting review of whether this is a genuine enquiry",
            reason=(
                opp.qualification_reason
                or "The conversation is not currently qualified as a sales opportunity"
            ),
            priority=Priority.LOW,
            reply_mode=ReplyMode.HOLD,
            human_intervention_required=False,
        )

    if escalated or opp.human_takeover:
        return NextBestAction(
            action="Human take-over: a representative is handling the customer",
            reason=(
                "A restricted case or an escalation trigger requires human handling; "
                "the assistant does not resume autonomous selling"
            ),
            priority=priority,
            reply_mode=ReplyMode.HANDOVER,
            human_intervention_required=True,
        )

    # A bare greeting with no other content is not a request for information: the
    # customer has not asked anything or stated a need yet, so answering with the
    # product catalogue (the ANSWER/NURTURE default for "no need identified")
    # reads as an unprompted info-dump. Checked after the three gates above, so a
    # real signal (withdrawal, a hold, an active escalation) still wins over a
    # coincidental greeting — not that one is likely to carry both at once.
    if det.greeting:
        return NextBestAction(
            action="Greet the customer and invite them to say what they need",
            reason="The message is a greeting with no stated need yet",
            priority=priority,
            reply_mode=ReplyMode.GREETING,
        )

    # ---- State rules -----------------------------------------------------

    if opp.state is OpportunityState.HIGH_INTENT:
        if Signal.COMPETITIVE in signals or opp.competitive_risk:
            return NextBestAction(
                action="Human sales intervention: address the competitive risk",
                reason="High intent alongside a competitive comparison — needs a person",
                priority=priority,
                reply_mode=ReplyMode.HANDOVER,
                human_intervention_required=True,
            )
        return NextBestAction(
            action="Contact the customer to close",
            reason="High purchase readiness — prioritise immediate sales contact",
            priority=priority,
            reply_mode=ReplyMode.CLOSE,
            human_intervention_required=True,
        )

    if opp.state is OpportunityState.EVALUATION_HESITATION:
        if priority is Priority.HIGH:
            return NextBestAction(
                action="Sales follow-up",
                reason="A high-value opportunity in evaluation — prioritise follow-up",
                priority=priority,
                reply_mode=ReplyMode.ADDRESS_CONCERN,
            )
        if Signal.COMPETITIVE in signals:
            return NextBestAction(
                action="Address the competitive concern and nurture",
                reason="Competitive comparison detected — restate the value proposition",
                priority=priority,
                reply_mode=ReplyMode.ADDRESS_CONCERN,
            )
        if Signal.HESITATION in signals:
            return NextBestAction(
                action="Nurture: identify the objection and address it",
                reason="Hesitation detected — respond with grounded information",
                priority=priority,
                reply_mode=ReplyMode.ADDRESS_CONCERN,
            )
        return NextBestAction(
            action="Address the concern with grounded information",
            reason="Continued evaluation — provide factual support",
            priority=priority,
            reply_mode=ReplyMode.ADDRESS_CONCERN,
        )

    if opp.state is OpportunityState.POTENTIAL_INTEREST:
        if signals & {Signal.EXPANSION_FAMILY, Signal.EXPANSION_CORPORATE}:
            return NextBestAction(
                action="Explore the expansion opportunity and recommend the right plan",
                reason="Expansion signal detected — identify the right product",
                priority=priority,
                reply_mode=ReplyMode.NURTURE,
            )
        return NextBestAction(
            action="Continue nurturing and clarify the need",
            reason="Early interest — nurture and guide toward the right plan",
            priority=priority,
            reply_mode=ReplyMode.NURTURE,
        )

    if opp.state is OpportunityState.COLD_LEAD:
        return NextBestAction(
            action="Answer and nurture: give basic information, clarify the need",
            reason="Cold lead — inform and identify the insurance need",
            priority=priority,
            reply_mode=ReplyMode.ANSWER,
        )

    if opp.state is OpportunityState.CLOSED_ACTIVE:
        if signals & {Signal.EXPANSION_FAMILY, Signal.EXPANSION_CORPORATE}:
            return NextBestAction(
                action="Create an expansion opportunity",
                reason="An existing customer with an expansion signal",
                priority=priority,
                reply_mode=ReplyMode.MAINTAIN,
            )
        if opp.churn_risk:
            return NextBestAction(
                action="Flag the retention risk and trigger a retention action",
                reason="Churn risk detected on an active customer",
                priority=priority,
                reply_mode=ReplyMode.HANDOVER,
                human_intervention_required=True,
            )
        return NextBestAction(
            action="Maintain the relationship",
            reason="Active customer — maintain engagement",
            priority=priority,
            reply_mode=ReplyMode.MAINTAIN,
        )

    if opp.state is OpportunityState.DORMANT_LOST:
        return NextBestAction(
            action="Schedule a follow-up to re-engage",
            reason="Dormant or lost — attempt re-engagement",
            priority=priority,
            reply_mode=ReplyMode.NURTURE,
        )

    return NextBestAction(
        action="Continue nurturing",
        reason="No specific rule matched",
        priority=priority,
        reply_mode=ReplyMode.ANSWER,
    )
