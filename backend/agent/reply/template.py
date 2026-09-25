# -*- coding: utf-8 -*-
"""Deterministic reply wording: the offline peer.

A full conversation completes on this alone, with no key and no network. That is what
makes a demo independent of a provider being reachable, and it is why this is a peer
rather than an emergency stub.

Every reply it produces is marked `generation="template"`, so a reader is never misled
into thinking a model chose the words.

Two compliance rules are enforced here rather than hoped for:

    a premium figure always carries the disclaimer, never truncated
    a handover, withdrawal or held reply contains no sales push

The second one is why the wording is organised by `ReplyMode` instead of by a single
template with conditionals — the modes where the assistant must stop selling are the
ones most likely to be got wrong by an edit somewhere else.
"""
from __future__ import annotations

import re

from ...domain.enums import Generation, ReplyMode
from . import ReplyOutcome, ReplyRequest

# Any currency figure triggers the disclaimer. Deliberately broad: a false positive
# adds a sentence, a false negative breaches a compliance red line.
_MONEY = re.compile(r"(S?\$|\bSGD\b)\s?\d")


def ensure_premium_disclaimer(text: str, disclaimer: str) -> tuple[str, bool]:
    """Enforce the approved disclaimer on the actual customer-facing wording."""
    if disclaimer and _MONEY.search(text) and disclaimer not in text:
        return f"{text}\n\n{disclaimer}", True
    return text, False

_READINESS_INVITATION = (
    "If you'd like a representative to help with the next step, reply 'I'm ready'. "
    "I'll ask you to confirm before notifying the team."
)

# Modes where the assistant does not sell. No facts, no figures, no next step.
_STANDALONE: dict[ReplyMode, str] = {
    ReplyMode.HANDOVER: (
        "A CareSure representative is handling this conversation. "
        "I'll leave the details with them."
    ),
    ReplyMode.WITHDRAWN: (
        "Understood. If anything changes, "
        "we're here whenever you want to pick it up again."
    ),
    ReplyMode.HOLD: (
        "I can't take this request further "
        "automatically, but I can still help with general plan information."
    ),
    ReplyMode.GREETING: (
        "Hello! I'm CareSure's AI assistant — what can I help you with today?"
    ),
}

_TEMPLATE_VARIANTS: dict[ReplyMode, dict[str, tuple[str, str]]] = {
    ReplyMode.ANSWER: {
        "answer_direct": ("", ""),
        "answer_detail": ("Here are the relevant details:", ""),
        "answer_open": ("", "Would you like me to clarify a specific part?"),
    },
    ReplyMode.NURTURE: {
        "nurture_direct": ("", ""),
        "nurture_detail": ("Here are the relevant details:", ""),
        "nurture_open": ("", "Which part would you like to explore?"),
    },
    ReplyMode.ADDRESS_CONCERN: {
        "concern_direct": ("", ""),
        "concern_detail": ("Here is the information I can confirm:", ""),
        "concern_open": ("", "Is there a specific part you would like clarified?"),
    },
}
_ACKNOWLEDGEMENTS = {"none": ""}


class TemplateComposer:
    """Assembles a reply from approved facts and fixed wording."""

    @staticmethod
    def template_ids_for(mode: ReplyMode) -> set[str]:
        return set(_TEMPLATE_VARIANTS.get(mode, {}))

    @staticmethod
    def template_descriptions_for(mode: ReplyMode) -> dict[str, str]:
        descriptions = {
            "answer_direct": "give the selected facts directly, without filler",
            "answer_detail": "introduce requested detail, then give the selected facts",
            "answer_open": "give the facts, then invite one specific clarification",
            "nurture_direct": "give the selected facts directly, without filler",
            "nurture_detail": "introduce requested detail, then give the selected facts",
            "nurture_open": "give the facts, then ask which part matters most",
            "concern_direct": "address the concern with the selected facts only",
            "concern_detail": "introduce confirmed detail, then give the facts",
            "concern_open": "give the facts, then offer one specific clarification",
        }
        return {
            template_id: descriptions[template_id]
            for template_id in _TEMPLATE_VARIANTS.get(mode, {})
        }

    @staticmethod
    def acknowledgement_ids() -> set[str]:
        return set(_ACKNOWLEDGEMENTS)

    def compose(self, request: ReplyRequest) -> ReplyOutcome:
        mode = request.action.reply_mode

        standalone = _STANDALONE.get(mode)
        if standalone is not None:
            return self._outcome(standalone, request, displayed_facts=[])

        if mode is ReplyMode.CLOSE and not request.facts:
            return self._outcome(
                "I can help arrange the next step with a representative. "
                "Reply 'I'm ready' and I'll ask you to confirm before notifying the team.",
                request,
            )

        opener, closer = _TEMPLATE_VARIANTS.get(mode, {}).get(
            request.template_id or "", ("", "")
        )
        if mode is ReplyMode.CLOSE:
            opener, closer = "", _READINESS_INVITATION
        # Reusing a transition phrase is more conspicuous than omitting it.
        # Prior assistant messages are context, not sources for product claims.
        recent_business = [
            message.text for message in (request.history or [])[-6:]
            if not getattr(message, "is_from_customer", False)
        ]
        if opener and any(opener in previous for previous in recent_business):
            opener = ""
        if closer and mode is not ReplyMode.CLOSE and any(
            closer in previous for previous in recent_business
        ):
            closer = ""
        lines = []
        if opener:
            lines.append(opener)
        if request.facts:
            # No "- " bullet prefix: each fact is a complete sentence already,
            # and the frontend renders each newline-separated line as its own
            # paragraph, so this reads as a short flowing message rather than
            # a formatted list.
            lines.extend(request.facts)
        else:
            # No grounded fact to offer. Say so rather than improvising, so the gap
            # is visible instead of being filled with something plausible.
            lines.append(
                "I can't confirm that from the information I have."
            )
        if closer and request.facts:
            lines.append(closer)
        return self._outcome("\n".join(lines), request)

    def _outcome(
        self, text: str, request: ReplyRequest, *, displayed_facts: list[str] | None = None
    ) -> ReplyOutcome:
        text, _ = ensure_premium_disclaimer(text, request.disclaimer)
        return ReplyOutcome(
            text=text,
            generation=Generation.TEMPLATE,
            displayed_facts=(
                list(request.facts) if displayed_facts is None else displayed_facts
            ),
            degraded=True,
            # Expected whenever this peer is the configured one. A model failing over
            # to it is a different matter, and `ModelComposer` reports that as a fault.
            by_design=True,
            degradation_reason="composed from a template; no model produced the wording",
            history=list(request.history or []),
        )
