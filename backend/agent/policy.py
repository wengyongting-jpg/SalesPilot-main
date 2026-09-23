# -*- coding: utf-8 -*-
"""System prompts, guardrails, and the customer-visibility boundary.

Two things live here because they are the same concern seen from two sides:
what the model is told to do, and what the model must never be told. The
frozen build's defect was concrete —

    # salespilot/response/llm_generator.py
    f"sales signals: {signals}; opportunity state: {opp.state.value}."

— an internal state name and a signal list, interpolated straight into a
prompt whose output the customer reads. `assert_customer_safe` makes that
class of defect a test failure instead of a code-review miss: it is run
against the *assembled* prompt text, not eyeballed.

`MAX_HISTORY_MESSAGES` gives the assembled prompt a fixed upper bound
regardless of how long the conversation has run (`docs/backend-plan.md`
§12.3), mirroring the frozen build's `_CONTEXT_WINDOW = 6`.
"""
from __future__ import annotations

from ..domain.enums import Intent, OpportunityState, Priority, Product, Signal
from ..domain.message import Message

MAX_HISTORY_MESSAGES = 6

# Generated from the enums, not restated, so a new state or signal is covered
# automatically instead of needing a second edit here.
#
# Matched case-SENSITIVELY, deliberately: `OpportunityState`, `Signal` and
# `Priority` wire values are Title Case or ALL CAPS (e.g. "Cold Lead",
# "Purchase", "LOW"). A customer-safe reply uses those same words freely in
# ordinary lowercase prose ("proceed with your purchase", "a low-cost plan"),
# so a case-insensitive check on single-word values like "Purchase" or "LOW"
# raised false positives on completely ordinary sentences. Matching the exact
# casing a raw enum interpolation would actually produce catches the real
# defect (`f"...state: {opp.state.value}"`) without banning ordinary English.
_ENUM_TOKENS: tuple[str, ...] = tuple(
    sorted(
        {member.value for member in OpportunityState}
        | {member.value for member in Signal}
        | {member.value for member in Priority}
    )
)

# Distinctive enough (multi-word, Title Case, or an acronym) that ordinary
# customer-facing English will not say them by accident — safe to check
# against both a developer-authored prompt and a model's own free-form reply.
_UNAMBIGUOUS_TOKENS: tuple[str, ...] = ("next best action", "HITL")

# Plain English words a helpful reply may legitimately use ("priority
# booking", "escalate to our hotline", "your qualification for this plan") —
# real leak indicators only when they show up in a *developer-authored*
# instruction or fact, never proof of one in the model's own generated
# wording. Checked on the prompt going in, deliberately excluded from the
# check on the model's reply coming back (`assert_reply_safe`), because that
# earlier, broader check caused the reply's own ordinary vocabulary to be
# misread as a leak and crash the turn.
_PROMPT_ONLY_TOKENS: tuple[str, ...] = ("score", "priority", "qualification", "escalat")

_FORBIDDEN_TOKENS: tuple[str, ...] = _ENUM_TOKENS + _UNAMBIGUOUS_TOKENS + _PROMPT_ONLY_TOKENS


def assert_customer_safe(text: str) -> None:
    """Raise if `text` contains an internal state name, signal, score, or priority band.

    This is red line 3 (`docs/backend-plan.md` §3): anything placed in a
    customer-reply prompt can appear in what the customer reads. Used on the
    assembled prompt before it is sent — `text` here is always
    developer-authored or KB content, never the model's own words, so the
    full, generous token set is safe to check without false positives.
    """
    hits = [token for token in _FORBIDDEN_TOKENS if token in text]
    if hits:
        raise ValueError(
            "customer-facing prompt leaks internal vocabulary: " + ", ".join(hits)
        )


def assert_reply_safe(text: str) -> None:
    """Raise if the model's own reply contains an internal state, signal, or
    priority band literally.

    Deliberately narrower than `assert_customer_safe`: `text` here is the
    model's free-form output, which may legitimately use ordinary words like
    "priority" or "escalate" in a normal customer-service sentence. Only the
    enum-derived and unambiguous tokens are checked, and the caller degrades
    to the template peer on failure rather than letting this propagate — a
    genuine leak should never reach the customer, but it also should not
    crash the turn.
    """
    hits = [token for token in _ENUM_TOKENS + _UNAMBIGUOUS_TOKENS if token in text]
    if hits:
        raise ValueError(
            "reply leaks internal vocabulary: " + ", ".join(hits)
        )


def _enum_values(enum_cls) -> str:
    return ", ".join(f'"{member.value}"' for member in enum_cls)


EXTRACTION_SYSTEM_PROMPT = (
    "You are the extraction step of an insurance sales assistant for CareSure "
    "Health Insurance. Read the customer's latest message, using the "
    "conversation so far only for context, and report what you observe. You "
    "may call the read-only tools available to you to check product facts "
    "before answering, including to compare two products. You never decide "
    "anything about the sale — no state, no score, no priority, no "
    "escalation — you only report what the message contains.\n\n"
    f"intent must be one of: {_enum_values(Intent)}.\n"
    f"product must be one of: {_enum_values(Product)}, or \"unknown\" if none is named.\n"
    f"signals may include any of: {_enum_values(Signal)}; leave empty if none apply.\n"
    "restricted is true only when the message needs personalised medical or "
    "underwriting judgement, a claim decision, a custom quotation, or an "
    "explicit request for a person.\n"
    "genuine_enquiry is false only when the message reads as advertising, a "
    "bot, or otherwise not a prospective customer asking about insurance."
)

REPLY_SYSTEM_PROMPT = (
    "You are writing one concise, warm WhatsApp-style reply for a CareSure "
    "Health Insurance customer. Use only the approved facts you are given — "
    "never invent a premium, coverage detail, eligibility rule, claims "
    "outcome, or underwriting decision. You are an AI assistant, not a human "
    "representative, and must never claim otherwise. Follow the instruction "
    "you are given for how to handle this turn; do not add sales pressure "
    "beyond what it asks for. If a premium figure appears in the facts you "
    "are given, append the disclaimer you are given verbatim."
)


def customer_safe_projection(
    *,
    escalate: bool = False,
    withdrawal: bool = False,
    takeover: bool = False,
    greeting: bool = False,
    hesitation: bool = False,
    high_intent: bool = False,
) -> str:
    """A plain instruction sentence with no internal state, signal, score, or
    priority band — what crosses from the deterministic kernel into the
    model's context for the composing step.

    Callers (eventually `services.conversation`) translate a kernel verdict
    into these primitive flags before calling in; this function never
    receives — and therefore cannot leak — the kernel's own vocabulary.
    """
    if withdrawal:
        instruction = (
            "The customer has said they do not want to proceed. Acknowledge "
            "this warmly and respectfully, and do not encourage them to "
            "reconsider or mention any plan, price, or next step."
        )
    elif takeover or escalate:
        instruction = (
            "A person is now handling this conversation directly. Write a "
            "brief, warm holding reply that reassures the customer without "
            "making any sales pitch or offering new information."
        )
    elif greeting:
        instruction = (
            "This is the customer's first message and it does not ask about "
            "anything specific yet. Greet them warmly, briefly say what you "
            "can help with, and ask which plan interests them — do not list "
            "detailed facts or premiums yet; save those for once they ask."
        )
    elif hesitation:
        instruction = (
            "The customer is weighing cost against value. Answer using only "
            "the approved facts, address their concern plainly, and do not "
            "push toward a decision."
        )
    elif high_intent:
        instruction = (
            "The customer is ready to move forward. Answer their question "
            "using the approved facts and offer a clear, low-pressure next "
            "step (for example, being connected to complete the application)."
        )
    else:
        instruction = (
            "Answer the customer's question using only the approved facts, "
            "and invite a follow-up question if something is unclear."
        )
    return instruction


def trim_history(messages: list[Message]) -> list[Message]:
    """The last `MAX_HISTORY_MESSAGES` messages, oldest first."""
    if len(messages) <= MAX_HISTORY_MESSAGES:
        return list(messages)
    return list(messages[-MAX_HISTORY_MESSAGES:])
