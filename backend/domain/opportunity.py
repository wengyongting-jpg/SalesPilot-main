# -*- coding: utf-8 -*-
"""The opportunity profile: the persistent memory of one customer conversation.

Holds where the customer is in the buying journey, what has been observed, how
valuable the opportunity looks, and the full transcript. Every business decision
about it is made in `backend.kernel`; this module only holds the state.

On counting, see `docs/v0.0/api/interface-v1.md` §1.1. The field is
`customer_message_count`, because that is what it counts. `turns` survives as a
read-only alias so the wire contract is unbroken, but it cannot be assigned, which
means no code inside the backend can use the misleading name to mutate state.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .enums import (
    Intent,
    MessageRole,
    OpportunityState,
    Priority,
    Product,
    Qualification,
    Signal,
)
from .decision import PendingAction
from .detection import BuyingPosture, ObservationEvidence
from .message import Message


def _now() -> datetime:
    return datetime.now()


@dataclass
class ScoreCard:
    """Two axes, scored separately, plus the priority derived from both.

    The previous build used one flat 100-point number built only from behaviour.
    There is no authoritative standard for lead scoring, but the industry
    convention is consistent on four points, and that model implemented one of
    them: fit and behaviour as **separate** axes, fit gating behaviour, negative
    scoring, and decay.

        Fit (0-100)        how appropriate and how valuable this opportunity is
            need_identified      40   is there a real need, and one we sell?
            product_potential    40   which plan, i.e. deal size
            expansion            20   family or corporate breadth

        Behaviour (0-100)  how actively they are buying right now
            purchase_intent      40
            purchase_readiness   30
            engagement           30   depth 14 + recency 10 + urgency 6

    Risk flags — competitive, compliance, human request — add no points on either
    axis. They drive next best action and escalation, so a risky opportunity is
    surfaced by the action rather than by an inflated number.

    `total` exists only so the existing wire field has a value. It is the mean of
    the two axes and is **display-only**: ranking uses `priority`, which is derived
    from the two axes as a matrix rather than by thresholding their average.
    Collapsing them into one number for ranking is the mistake this redesign
    exists to undo.
    """

    # Fit axis
    need_identified: int = 0
    product_potential: int = 0
    expansion: int = 0
    fit_total: int = 0

    # Behaviour axis. Reported in parts so the admin surface can show *why* a
    # number is what it is: "behaviour 29" is not reviewable, "82 raw, decayed to
    # 35% after 40 days of silence" is.
    purchase_intent: int = 0
    purchase_readiness: int = 0
    engagement: int = 0
    engagement_depth: int = 0
    engagement_urgency: int = 0
    behaviour_raw: int = 0
    # Recency as a percentage factor, 100 for a live conversation down to a floor
    # for an abandoned one. It multiplies the raw behaviour rather than adding to
    # it: decay means stale behavioural evidence counts for less, and an additive
    # term worth a tenth of the axis cannot express that.
    engagement_recency: int = 100
    behaviour_total: int = 0

    # Derived
    total: int = 0
    priority: Priority = Priority.LOW


@dataclass
class QualificationVerdict:
    """The outcome of the qualification gate, with its evidence.

    `evidence` is carried so the admin surface and the agent run record can show
    *why* a conversation was held. A hold that appears as an opaque boolean is not
    reviewable, and a judgement that cannot be reviewed should not be acted on.
    """

    level: Qualification = Qualification.QUALIFIED
    reason: Optional[str] = None
    evidence: list[str] = field(default_factory=list)

    @property
    def is_sellable(self) -> bool:
        return self.level is Qualification.QUALIFIED


@dataclass
class StateHistoryEntry:
    timestamp: datetime
    from_state: str
    to_state: str
    reason: str


@dataclass
class ScoreHistoryEntry:
    timestamp: datetime
    score: int
    state: str
    trigger: str
    evidence: dict = field(default_factory=dict)


@dataclass
class Opportunity:
    id: str
    customer_name: str

    state: OpportunityState = OpportunityState.COLD_LEAD
    product: Product = Product.UNKNOWN

    # Signals currently in force, and every signal ever observed.
    signals: list[Signal] = field(default_factory=list)
    signal_history: list[Signal] = field(default_factory=list)
    main_concern: Optional[str] = None

    # Flags, not states: a customer occupies one state while carrying any
    # combination of these.
    competitive_risk: bool = False
    churn_risk: bool = False
    compliance_risk: bool = False
    expansion: list[str] = field(default_factory=list)

    last_intent: Intent = Intent.GENERIC
    # The strongest buying intent observed so far. A persistent high-water mark,
    # so a later vague message cannot erase intent the conversation established.
    best_intent: Intent = Intent.GENERIC
    # Whether urgency has ever been expressed. Also a high-water mark, for the same
    # reason: the previous build inspected only the current message, so "I need this
    # urgently" was forgotten on the following turn — inconsistent with how
    # `best_intent` treats the very same kind of evidence.
    urgency_observed: bool = False

    # How many messages the customer has sent. Not agent runs, not model calls,
    # not tool calls — see interface-v1 §1.1 for why the distinction matters.
    customer_message_count: int = 0

    score: Optional[ScoreCard] = None
    score_history: list[ScoreHistoryEntry] = field(default_factory=list)
    state_history: list[StateHistoryEntry] = field(default_factory=list)

    # Human-in-the-loop.
    human_takeover: bool = False
    human_intervention_required: bool = False
    # A proposed handoff is not a case. It becomes one only after the customer
    # explicitly confirms, including when the trigger came from a model tool.
    pending_handoff_reason: Optional[str] = None
    pending_action: Optional[PendingAction] = None
    buying_posture: BuyingPosture = BuyingPosture.UNKNOWN
    posture_evidence: list[ObservationEvidence] = field(default_factory=list)
    pending_question_field: Optional[str] = None
    collected_answers: dict[str, str] = field(default_factory=dict)
    evidence_sources: dict[str, str] = field(default_factory=dict)

    # Qualification gate. The machine may only ever raise this to HELD; only a
    # human sets DISQUALIFIED.
    qualification: Qualification = Qualification.QUALIFIED
    qualification_reason: Optional[str] = None
    # How many messages have been observed as soliciting rather than enquiring.
    # Two strikes are required for a machine hold, so a single misjudged message
    # cannot remove a genuine customer from the queue.
    solicitation_count: int = 0

    messages: list[Message] = field(default_factory=list)
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)

    @property
    def last_customer_message_at(self) -> Optional[datetime]:
        """When the customer last said anything. Drives engagement recency decay.

        Derived rather than stored so it cannot fall out of step with the
        transcript.
        """
        for message in reversed(self.messages):
            if message.role is MessageRole.CUSTOMER:
                return message.ts
        return None

    @property
    def is_sellable(self) -> bool:
        """Whether the assistant may advance the sale at all."""
        return self.qualification is Qualification.QUALIFIED

    @property
    def turns(self) -> int:
        """Deprecated alias of `customer_message_count`, kept for the wire.

        Read-only on purpose. `interface-v1.md` §1.1 deprecates the name because it
        is routinely read as "agent turns", which it has never been; making it
        unassignable ensures the truthful name is the only one that can drive
        state.
        """
        return self.customer_message_count

    @property
    def priority(self) -> Optional[Priority]:
        return self.score.priority if self.score else None

    @property
    def final_score(self) -> Optional[int]:
        return self.score.total if self.score else None
