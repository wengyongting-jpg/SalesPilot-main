# -*- coding: utf-8 -*-
"""What was understood from one customer message, and what was retrieved for it.

`Detection` is the output of the extraction step, whether a model or the rule-based
peer produced it. `RetrievalResult` is the output of knowledge retrieval.

Both are plain data. Neither carries a decision: the state transition, the score,
the priority, the next best action and the escalation are all computed from these
in `backend.kernel`, which is the only layer allowed to decide anything.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .enums import Intent, Product, Signal


@dataclass
class Detection:
    intent: Intent = Intent.GENERIC
    product: Product = Product.UNKNOWN
    signals: list[Signal] = field(default_factory=list)
    concerns: list[str] = field(default_factory=list)
    # True when the message touches something outside the assistant's authority:
    # a personalised medical or underwriting question, a claim decision, a custom
    # quotation, or an explicit request for a person.
    restricted: bool = False

    # ---- Lifecycle observations -----------------------------------------
    # Two text judgements the previous build made *inside* the state machine, by
    # importing the signal detector into the engine. That was a layering
    # inversion: the deterministic core reached back into the extraction layer,
    # and the rebuild's architecture test now rejects it. They are observations,
    # so they belong here; the kernel reads them and decides.
    cancellation: bool = False
    postponement: bool = False

    # ---- Qualification observations --------------------------------------
    # `genuine_enquiry` is a semantic judgement: is this a prospective customer at
    # all, rather than advertising, a bot or an unrelated message? A model answers
    # it well and a keyword list answers it badly, which is exactly why it enters
    # as a typed observation rather than being inferred from a score.
    genuine_enquiry: bool = True
    # `solicitation` is the deterministic corroboration: the sender is offering or
    # promoting something rather than asking about cover. Produced by the
    # rule-based peer, so it is available with no model configured.
    solicitation: bool = False


@dataclass
class KnowledgeMatch:
    product_id: str
    field: str
    snippet: str
    score: int


@dataclass
class RetrievalResult:
    """Approved knowledge-base facts, with a confidence in the match.

    `facts` stays a structured array rather than prose: the customer app builds
    product cards from the individual entries, and a weak match must be detectable
    as such so the assistant escalates instead of guessing.
    """

    facts: list[str] = field(default_factory=list)
    matches: list[KnowledgeMatch] = field(default_factory=list)
    confidence: float = 0.0
    product: Product = Product.UNKNOWN

    @property
    def is_confident(self) -> bool:
        return self.confidence >= 0.5


@dataclass
class HandoffProposal:
    """A handover *suggested* by the model through `request_human_handoff`.

    Deliberately not a decision. `backend.kernel.hitl` reads this as one input
    among several and decides for itself; the model cannot open a case. Keeping the
    proposal separate from the outcome is what lets the telemetry show that the
    model asked and the kernel declined.
    """

    requested: bool = False
    reason: Optional[str] = None
