# -*- coding: utf-8 -*-
"""Domain models: enums and dataclasses flowing through the Agent Workflow.

Six core opportunity states (Expansion and Churn are flags, not states):
  1. Cold Lead
  2. Potential Interest
  3. Evaluation & Hesitation
  4. High Intent
  5. Closed / Active Customer
  6. Dormant / Lost
"""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


def now() -> datetime:
    return datetime.now()


class Intent(str, Enum):
    """Customer intent — what the customer is asking about."""

    GENERIC = "generic"
    PRICE = "price"
    COVERAGE = "coverage"
    ELIGIBILITY = "eligibility"
    CLAIMS = "claims"
    WAITING_PERIOD = "waiting_period"
    PAYMENT = "payment"
    APPLICATION = "application"
    COMPARISON = "comparison"
    FAMILY_NEED = "family_need"
    CORPORATE_NEED = "corporate_need"
    UNDERWRITING = "underwriting"
    HUMAN_REQUEST = "human_request"
    COMPLAINT = "complaint"


class Product(str, Enum):
    ESSENTIAL = "essential"
    FAMILY = "family"
    PLUS = "plus"
    CORPORATE = "corporate"
    UNKNOWN = "unknown"


class OpportunityState(str, Enum):
    """Six core opportunity states.

    Expansion Opportunity and Churn Risk are NOT separate states —
    they are flags attached to the Opportunity profile.
    """

    COLD_LEAD = "Cold Lead"
    POTENTIAL_INTEREST = "Potential Interest"
    EVALUATION_HESITATION = "Evaluation & Hesitation"
    HIGH_INTENT = "High Intent"
    CLOSED_ACTIVE = "Closed / Active Customer"
    DORMANT_LOST = "Dormant / Lost"


class Signal(str, Enum):
    """Observable sales signals — distinct from intent and state.

    Intent  = what the customer is asking.
    State   = where the customer is in the buying journey.
    Signal  = observable evidence from the conversation.
    """

    PURCHASE = "Purchase"
    PURCHASE_PREPARATION = "Purchase Preparation"
    HESITATION = "Hesitation"
    COMPETITIVE = "Competitive"
    EXPANSION_FAMILY = "Expansion: Family"
    EXPANSION_CORPORATE = "Expansion: Corporate"
    HUMAN_REQUEST = "Human Request"
    COMPLIANCE_RISK = "Compliance Risk"
    NEGOTIATION = "Negotiation"   # commercial negotiation / discount / price match
    CONVERSION = "Conversion"
    WITHDRAWAL = "Withdrawal"


class Priority(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class CaseStatus(str, Enum):
    OPEN = "Open"
    TAKEN_OVER = "Taken Over"
    CLOSED = "Closed"


@dataclass
class Message:
    role: str                 # "customer" | "agent" — the side of the
    #                           conversation, a deliberately closed set. Who
    #                           *authored* an agent-side message (AI vs a human
    #                           representative) is a separate axis and is not
    #                           encoded here.
    text: str
    ts: datetime = field(default_factory=now)
    # P0-5: client-generated idempotency key for the request that produced this
    # message. Set only on customer messages sent with one; None otherwise.
    client_message_id: Optional[str] = None


@dataclass
class Detection:
    """Detection result for a single message, using conversation history."""

    intent: Intent = Intent.GENERIC
    product: Product = Product.UNKNOWN
    signals: list[Signal] = field(default_factory=list)
    concerns: list[str] = field(default_factory=list)
    restricted: bool = False


@dataclass
class KnowledgeMatch:
    product_id: str
    field: str
    snippet: str
    score: int


@dataclass
class RetrievalResult:
    """Knowledge retrieval result (RAG: keyword or semantic + confidence)."""

    facts: list[str] = field(default_factory=list)
    matches: list[KnowledgeMatch] = field(default_factory=list)
    confidence: float = 0.0
    product: Product = Product.UNKNOWN


@dataclass
class ScoreCard:
    """Opportunity Value Score (100 points).

    Dimensions:
      Purchase Intent       30
      Purchase Readiness    20
      Product Potential     20
      Expansion Opportunity 15
      Engagement & Urgency  15

    Risk flags (competitive / compliance / human request) do NOT add points;
    they drive Next Best Action / HITL instead.
    """

    purchase_intent: int = 0
    purchase_readiness: int = 0
    product_potential: int = 0
    expansion: int = 0
    engagement: int = 0
    total: int = 0
    priority: Priority = Priority.LOW


@dataclass
class NextBestAction:
    """Structured recommendation from the decision engine."""

    action: str
    reason: str
    priority: Priority
    human_intervention_required: bool = False


@dataclass
class StateHistoryEntry:
    """A single state transition record."""

    timestamp: datetime
    from_state: str
    to_state: str
    reason: str


@dataclass
class ScoreHistoryEntry:
    """A single score recalculation record."""

    timestamp: datetime
    score: int
    state: str
    trigger: str   # what caused the recalculation (e.g. "new_message", "state_change")


@dataclass
class Opportunity:
    """Customer opportunity profile.

    Tracks the full sales opportunity: where the customer is in the buying
    journey, what signals have been observed, how valuable the opportunity is,
    and what the sales rep should do next.
    """

    id: str
    customer_name: str
    state: OpportunityState = OpportunityState.COLD_LEAD
    product: Product = Product.UNKNOWN
    signals: list[Signal] = field(default_factory=list)  # active signals
    signal_history: list[Signal] = field(default_factory=list)  # all ever detected
    main_concern: Optional[str] = None

    # Risk / opportunity flags (NOT states)
    competitive_risk: bool = False
    churn_risk: bool = False
    compliance_risk: bool = False
    expansion: list[str] = field(default_factory=list)

    # Context
    last_intent: Intent = Intent.GENERIC
    # Strongest buying intent observed so far (persistent high-water mark used
    # for scoring, so a later generic message cannot erase established intent).
    best_intent: Intent = Intent.GENERIC
    turns: int = 0

    # Scoring
    score: Optional[ScoreCard] = None
    score_history: list[ScoreHistoryEntry] = field(default_factory=list)
    state_history: list[StateHistoryEntry] = field(default_factory=list)

    # HITL
    human_takeover: bool = False
    human_intervention_required: bool = False

    # Conversation
    messages: list[Message] = field(default_factory=list)
    created_at: datetime = field(default_factory=now)
    updated_at: datetime = field(default_factory=now)


@dataclass
class HumanCase:
    """Human escalation case (HITL Case Template)."""

    id: str
    opportunity_id: str
    customer_name: str
    state: OpportunityState
    product: Product
    reason: str
    summary: str
    recommended_action: str
    status: CaseStatus = CaseStatus.OPEN
    created_at: datetime = field(default_factory=now)
