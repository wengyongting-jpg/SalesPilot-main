# -*- coding: utf-8 -*-
"""Every enumeration that reaches the wire.

**This module is the single source of truth.** The structured-output schemas the
model is given, the tool signatures it may call, and the serialisers the API uses
are all derived from these definitions rather than restating them.

That is not stylistic. In the previous build the extraction prompt and these
enums were two hand-maintained copies of one truth, and they drifted: the prompt
offered `"medical_question"` where the domain defined `"underwriting"`, and listed
seven of the eleven signals. The result was three escalation triggers that could
never fire whenever a model was configured, with no error and no log line. Nothing
in the code prevented it, so it happened.

The contract for these strings is `docs/v0.0/api/interface-v1.md` §4.3 and §1.2, and
`backend/tests/test_domain.py` compares the values against an independent
transcription of it.
"""
from enum import Enum


class Intent(str, Enum):
    """What the customer is asking about.

    Distinct from Signal (observable evidence) and OpportunityState (position in
    the buying journey). Conflating them is a recurring source of confusion, so
    the three live in three enums.
    """

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
    # A personalised medical or eligibility-assessment question. Named for the
    # business process it triggers, not for its surface wording. There is
    # deliberately no `medical_question` synonym: the model is offered this exact
    # value, so it cannot answer with one the domain rejects.
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
    """Position in the buying journey. Exactly six, in funnel order.

    Expansion Opportunity and Churn Risk are NOT states — they are flags on the
    opportunity profile, because a customer can be in exactly one state while
    carrying any combination of flags.
    """

    COLD_LEAD = "Cold Lead"
    POTENTIAL_INTEREST = "Potential Interest"
    EVALUATION_HESITATION = "Evaluation & Hesitation"
    HIGH_INTENT = "High Intent"
    CLOSED_ACTIVE = "Closed / Active Customer"
    DORMANT_LOST = "Dormant / Lost"


class Signal(str, Enum):
    """Observable evidence from the conversation.

    All eleven are offered to the model. The previous build offered seven, which
    made Withdrawal, Conversion, Negotiation and Purchase Preparation
    undetectable whenever a model was configured.
    """

    PURCHASE = "Purchase"
    PURCHASE_PREPARATION = "Purchase Preparation"
    HESITATION = "Hesitation"
    COMPETITIVE = "Competitive"
    EXPANSION_FAMILY = "Expansion: Family"
    EXPANSION_CORPORATE = "Expansion: Corporate"
    HUMAN_REQUEST = "Human Request"
    COMPLIANCE_RISK = "Compliance Risk"
    # Commercial negotiation: a discount or price-match request. Distinct from a
    # price *concern*, which is Hesitation. Escalates with its own reason and must
    # never be reported as a medical, underwriting or compliance matter.
    NEGOTIATION = "Negotiation"
    CONVERSION = "Conversion"
    WITHDRAWAL = "Withdrawal"


class Priority(str, Enum):
    """Sales prioritisation band, derived from the opportunity value score.

    Never used for eligibility, pricing, underwriting or claims decisions.
    """

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class CaseStatus(str, Enum):
    OPEN = "Open"
    TAKEN_OVER = "Taken Over"
    CLOSED = "Closed"


# ---- The three message axes ----------------------------------------------
# Three orthogonal questions, three fields. `docs/v0.0/api/interface-v1.md` §1 records
# what a single field answering two of them costs: `role: "agent"` made a human
# representative's message read as a contradiction, and a reader had to consult a
# second field to undo a confusion the first one created.


class MessageRole(str, Enum):
    """*Which side* of the conversation. A closed set of two.

    `BUSINESS` replaced an earlier `"agent"`, which implied "AI agent" and so was
    wrong for the human and system cases that share this side. The value names the
    party and implies nothing about who wrote it or how. There is no transitional
    alias, because a closed set with a deprecated member is not closed.
    """

    CUSTOMER = "customer"
    BUSINESS = "business"


class MessageAuthor(str, Enum):
    """*Who* wrote a business-side message.

    Deliberately excludes a customer value: if it had one, `role` would be
    derivable from `author` and the two could drift apart. Customer messages carry
    `author = None`.
    """

    AI = "ai"
    HUMAN = "human"
    SYSTEM = "system"


class KnowledgeField(str, Enum):
    """The fields of a product the assistant may quote.

    A closed set for the same reason the other enums are: the model is offered these
    exact values as a tool argument, so it cannot ask for a field the knowledge base
    has no answer for and then receive an improvised one.
    `backend/tests/test_agent_shell.py` asserts that every value here exists on every
    product, which binds the enum to the data rather than hoping they agree.
    """

    POSITIONING = "positioning"
    TARGET_CUSTOMER = "target_customer"
    ELIGIBILITY = "eligibility"
    COVERAGE = "coverage"
    PREMIUM = "premium"
    DEDUCTIBLE = "deductible"
    LIMITS = "limits"
    WAITING_PERIOD = "waiting_period"
    EXCLUSIONS = "exclusions"
    CLAIMS = "claims"
    PAYMENT = "payment"
    RENEWAL = "renewal"


class ReplyMode(str, Enum):
    """How the assistant should pitch its reply, as decided by the kernel.

    This is the only part of the kernel's verdict allowed to influence what the
    customer reads, and it exists so that influence can happen without leaking.
    The next best action is an instruction to a *representative* — "prioritise
    immediate sales contact" — and forwarding its wording into a customer-facing
    prompt invites the model to repeat it. A mode is an abstraction over the
    decision: the kernel chooses it, and `agent.policy` owns the wording.
    """

    ANSWER = "answer"
    NURTURE = "nurture"
    ADDRESS_CONCERN = "address_concern"
    CLOSE = "close"
    HANDOVER = "handover"
    WITHDRAWN = "withdrawn"
    HOLD = "hold"
    MAINTAIN = "maintain"


class Qualification(str, Enum):
    """Whether this conversation belongs in the sales queue at all.

    Separate from the score on purpose. A spammer is not a low-scoring customer;
    it is not a customer. The previous build had no such concept, so advertising
    traffic was scored as though it were buying: measured on the frozen build, spam
    that borrowed insurance vocabulary reached 96 points and outranked a genuine
    customer at 82.

    Three levels, and the machine may only reach the middle one:

        QUALIFIED      the default
        HELD           machine-settable. The assistant stops advancing the sale,
                       the conversation leaves the sales queue and appears in a
                       separate held list that a human releases with one action.
                       Still answered politely; abuse and complaints still escalate.
        DISQUALIFIED   a human decision only.

    The point of that asymmetry is that the judgement comes from a model and can be
    wrong, so the cost of being wrong is made small and reversible instead of the
    judgement being assumed accurate. A false hold costs a cooler reply and one
    click; it never loses the lead or the data.
    """

    QUALIFIED = "qualified"
    HELD = "held"
    DISQUALIFIED = "disqualified"


class Generation(str, Enum):
    """*How* a business-side message was produced.

    `TEMPLATE` means no model was involved at all — the offline path. A reader must
    never be led to believe a template reply came from a model, which is why this
    is reported rather than inferred. `docs/v0.0/api/interface-v1.md` §5.7.
    """

    LLM = "llm"
    TEMPLATE = "template"
    HUMAN = "human"
