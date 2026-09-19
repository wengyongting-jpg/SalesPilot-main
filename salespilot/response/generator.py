# -*- coding: utf-8 -*-
"""Customer reply generator — template version (swappable for an LLM).

Produces four reply modes based on the opportunity state and signals:
  - Answer: factual grounded reply to a product question
  - Nurture: warm, empathetic reply when the customer is hesitant or early
  - Follow-up: action-oriented reply guiding the customer to the next step
  - Human Handoff: deterministic escalation message (never LLM-generated)

Constraints:
  - Product facts can only come from the knowledge-base snippets.
  - General information carries the demo disclaimer when pricing is shown.
  - Escalation scenarios never give personalised insurance conclusions.
"""
from .. import config
from ..models import (
    Detection,
    HumanCase,
    Intent,
    NextBestAction,
    Opportunity,
    OpportunityState,
    RetrievalResult,
    Signal,
)

_GENERIC_HELP = (
    "Hi! I'm SalesPilot, CareSure's AI sales assistant. I can help with plan "
    "information, indicative premiums, coverage, eligibility, claims process "
    "and applications. Which plan would you like to know about: Essential, "
    "Family, Plus or Corporate?"
)

_NURTURE_OPENERS = (
    "I completely understand — choosing the right health cover is an important decision.",
    "Thanks for sharing that — it helps me guide you to the right plan.",
    "That's a great question. Let me help you think through this.",
    "I appreciate you sharing that. Here's what I can tell you:",
)

_FOLLOWUP_CLOSERS = {
    "nurture": "Would you like me to walk you through the plan options, or is there a specific concern I can address?",
    "follow_up": "If you'd like to move forward, I can connect you with a CareSure sales representative who can help with the next steps.",
    "info": "Let me know if you'd like more details on any of these, or if you have a specific question about coverage or pricing.",
}


class ResponseGenerator:
    def generate(
        self,
        opp: Opportunity,
        det: Detection,
        retrieval: RetrievalResult,
        case: HumanCase | None,
        nba: NextBestAction | None = None,
    ) -> str:
        # Human Handoff mode — deterministic, never LLM-generated
        if case is not None:
            return self._escalation_message(det, case)

        # --- P0-3: Human takeover is active — do NOT resume autonomous sales ---
        # Once a human has taken over, the AI must not generate sales
        # persuasion. It gives a neutral holding reply and lets the human
        # handle the customer. (The pipeline still logs the message and
        # updates internal signals/state.)
        if opp.human_takeover:
            return self._takeover_message()

        # --- P0-2: Withdrawal — acknowledge, never push sales ---
        if Signal.WITHDRAWAL in det.signals:
            return self._withdrawal_message()

        # Generic first contact
        if det.intent == Intent.GENERIC and opp.turns <= 1:
            return _GENERIC_HELP

        # Unknown product: return the approved four-plan overview
        if opp.product.name == "UNKNOWN":
            lines = retrieval.facts
            return (
                "Sure, here is a quick overview of the CareSure plans:\n"
                + "\n".join(lines[1:])
                + "\n\nYou can tell me whether cover is for yourself, your "
                "family, or your company, and I can point you to a suitable plan."
            )

        # Determine reply mode from state + signals
        mode = self._determine_mode(opp, det)

        # Build the reply
        if mode == "nurture":
            return self._nurture_reply(opp, det, retrieval)
        elif mode == "follow_up":
            return self._follow_up_reply(opp, det, retrieval)
        else:
            return self._answer_reply(opp, det, retrieval)

    @staticmethod
    def _determine_mode(opp: Opportunity, det: Detection) -> str:
        """Determine the reply mode: answer, nurture, or follow_up."""
        # Hesitation or early stage → nurture
        if (
            Signal.HESITATION in det.signals
            or opp.state == OpportunityState.COLD_LEAD
            or opp.state == OpportunityState.POTENTIAL_INTEREST
        ):
            return "nurture"

        # High intent or application → follow-up
        if (
            opp.state == OpportunityState.HIGH_INTENT
            or det.intent == Intent.APPLICATION
            or Signal.PURCHASE in det.signals
        ):
            return "follow_up"

        # Default: factual answer
        return "answer"

    @staticmethod
    def _answer_reply(opp, det, retrieval) -> str:
        parts = ["Thanks for reaching out. Here is what I can share:"]
        parts.extend(f"- {fact}" for fact in retrieval.facts[:4])
        if any("premium" in fact.lower() for fact in retrieval.facts):
            parts.append(config.DEMO_DISCLAIMER)
        return "\n".join(parts)

    @staticmethod
    def _nurture_reply(opp, det, retrieval) -> str:
        import random
        opener = random.choice(_NURTURE_OPENERS)
        parts = [opener]
        parts.extend(f"- {fact}" for fact in retrieval.facts[:3])

        if Signal.HESITATION in det.signals:
            parts.append(
                "I understand price matters — the indicative premium depends "
                "on the plan and underwriting, and a sales representative can "
                "walk you through the value."
            )
        if Signal.COMPETITIVE in det.signals:
            parts.append(
                "I can only share CareSure-approved facts rather than compare "
                "other insurers; a sales representative can discuss value with you."
            )
        if Signal.EXPANSION_FAMILY in det.signals:
            parts.append(
                "Adding family members is subject to the plan's age, "
                "dependency and underwriting rules; a representative can "
                "confirm who can be included."
            )
        elif Signal.EXPANSION_CORPORATE in det.signals:
            parts.append(
                "For employee / corporate cover, a corporate sales "
                "representative can assess your company's needs."
            )

        parts.append(_FOLLOWUP_CLOSERS["nurture"])
        if any("premium" in fact.lower() for fact in retrieval.facts):
            parts.append(config.DEMO_DISCLAIMER)
        return "\n".join(parts)

    @staticmethod
    def _follow_up_reply(opp, det, retrieval) -> str:
        parts = ["Great to hear you're interested! Here's a quick summary:"]
        parts.extend(f"- {fact}" for fact in retrieval.facts[:3])

        if det.intent == Intent.APPLICATION:
            parts.append(
                "If you would like to proceed, I can arrange for a CareSure "
                "sales representative to support your application."
            )
        if Signal.COMPETITIVE in det.signals or opp.competitive_risk:
            parts.append(
                "I notice you're comparing options — a sales representative "
                "can walk you through the full value proposition and help you "
                "make an informed decision."
            )

        parts.append(_FOLLOWUP_CLOSERS["follow_up"])
        if any("premium" in fact.lower() for fact in retrieval.facts):
            parts.append(config.DEMO_DISCLAIMER)
        return "\n".join(parts)

    @staticmethod
    def _withdrawal_message() -> str:
        """P0-2: neutral, respectful reply when the customer withdraws.

        Must NOT contain any positive purchase/sales-pushing language.
        """
        return (
            "Thanks for letting me know, and no problem at all. I completely "
            "respect your decision and won't push anything further. If your "
            "needs change in the future, I'm here whenever you'd like to pick "
            "things up again. Wishing you all the best."
        )

    @staticmethod
    def _takeover_message() -> str:
        """P0-3: neutral holding reply while a human handles the case.

        The AI does not make autonomous sales decisions once a human has
        taken over; it simply reassures the customer that a human is on it.
        """
        return (
            "Thanks for your message. A CareSure representative is now "
            "personally looking after your case and will follow up with you "
            "directly. I've passed along what you've shared so they have the "
            "full context."
        )

    @staticmethod
    def _escalation_message(det: Detection, case: HumanCase) -> str:
        if det.intent == Intent.COMPLAINT:
            return (
                "I'm sorry for the experience. I have opened a case and a "
                "human CareSure representative will follow up with you shortly."
            )
        if Signal.HUMAN_REQUEST in det.signals:
            return (
                "Of course. I've arranged for a human sales representative to "
                "contact you. They will assist with your request directly."
            )
        return (
            "Thank you. This needs a human specialist to handle properly, so "
            "I've created a case for a CareSure representative to follow up. "
            "They can give you accurate, personalised assistance on this matter."
        )
