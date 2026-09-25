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

_OPENERS: dict[ReplyMode, str] = {
    ReplyMode.ANSWER: "Here's what I can confirm{name}:",
    ReplyMode.NURTURE: "Happy to help{name}. Here's a quick overview:",
    ReplyMode.ADDRESS_CONCERN: (
        "That's a fair thing to weigh up{name}. Here are the facts as they stand:"
    ),
    ReplyMode.CLOSE: "Of course{name}. Here's what applies:",
    ReplyMode.MAINTAIN: "Thanks for getting in touch{name}. Here's the position:",
}

_CLOSERS: dict[ReplyMode, str] = {
    ReplyMode.ANSWER: "Anything else you'd like me to check?",
    ReplyMode.NURTURE: "Which of these sounds closest to what you need?",
    ReplyMode.ADDRESS_CONCERN: (
        "Take whatever time you need — I'm happy to go through any of it again."
    ),
    ReplyMode.CLOSE: (
        "A CareSure representative can take you through the next steps whenever "
        "you're ready."
    ),
    ReplyMode.MAINTAIN: "Let me know if there's anything else about your policy.",
}

# Modes where the assistant does not sell. No facts, no figures, no next step.
_STANDALONE: dict[ReplyMode, str] = {
    ReplyMode.HANDOVER: (
        "Thanks{name} — a CareSure representative is picking this up and will be in "
        "touch with you directly. I'll leave it with them from here."
    ),
    ReplyMode.WITHDRAWN: (
        "Understood{name}, and thanks for letting me know. If anything changes, "
        "we're here whenever you want to pick it up again."
    ),
    ReplyMode.HOLD: (
        "Thanks for your message{name}. A colleague will review it and come back to "
        "you if we can help."
    ),
    ReplyMode.GREETING: (
        "Hello{name}! I'm CareSure's assistant — what can I help you with today?"
    ),
}

_AI_NOTE = "(You're chatting with CareSure's AI assistant.)"


class TemplateComposer:
    """Assembles a reply from approved facts and fixed wording."""

    def compose(self, request: ReplyRequest) -> ReplyOutcome:
        mode = request.action.reply_mode
        name = f" {request.customer_name}" if request.customer_name else ""

        standalone = _STANDALONE.get(mode)
        if standalone is not None:
            return self._outcome(standalone.format(name=name), request)

        lines = [_OPENERS.get(mode, _OPENERS[ReplyMode.ANSWER]).format(name=name)]
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
                "I don't have a confirmed answer to hand, so I'd rather not guess."
            )
        lines.append(_CLOSERS.get(mode, _CLOSERS[ReplyMode.ANSWER]))
        return self._outcome("\n".join(lines), request)

    def _outcome(self, text: str, request: ReplyRequest) -> ReplyOutcome:
        text, _ = ensure_premium_disclaimer(text, request.disclaimer)
        return ReplyOutcome(
            text=text,
            generation=Generation.TEMPLATE,
            degraded=True,
            # Expected whenever this peer is the configured one. A model failing over
            # to it is a different matter, and `ModelComposer` reports that as a fault.
            by_design=True,
            degradation_reason="composed from a template; no model produced the wording",
            history=list(request.history or []),
        )
