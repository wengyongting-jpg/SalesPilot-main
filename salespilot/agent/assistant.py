# -*- coding: utf-8 -*-
"""SalesPilot main agent orchestration.

Pipeline (per customer message):

  1.  Context — load/create opportunity, append message, build context window
  2.  Intent & Context Understanding — LLM or rule-based extraction of
      intent, product, signals, and main concern
  3.  Opportunity State Detection — state machine transition
  4.  Sales Signal Detection — signals are part of extraction; accumulated here
  5.  Update Opportunity Profile — signals, flags, concerns, product
  6.  Opportunity Value Score — 100-point deterministic model
  7.  Priority — HIGH / MEDIUM / LOW band (from score)
  8.  Next Best Action — structured recommendation
  9.  Compliance / Permission Check — HITL escalation
 10.  RAG Retrieval — factual product knowledge (for response + confidence)
 11.  Answer / Nurture / Follow-up / Human Handoff — response generation
 12.  Save Decision + Score History — persist + log

LLM role: extraction (steps 2-4) — intent, product, signals, concern.
Deterministic role: state, score, priority, NBA, HITL, persistence.
The LLM never calculates the score or makes business decisions.
"""
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from .. import config
from ..detection import LLMExtractor, ExtractionResult
from ..detection.intent import IntentClassifier
from ..detection.product import ProductClassifier
from ..detection.signals import SignalDetector
from ..engine import (
    DecisionEngine,
    HITLManager,
    OpportunityStateMachine,
    PriorityEngine,
)
from ..knowledge import KnowledgeRetriever
from ..logging_utils import setup_logging
from ..models import (
    CaseStatus,
    Detection,
    HumanCase,
    Intent,
    Message,
    NextBestAction,
    Opportunity,
    Product,
    RetrievalResult,
    ScoreCard,
    ScoreHistoryEntry,
    Signal,
    StateHistoryEntry,
)
from ..response import ResponseGenerator
from ..storage import Repository

_CONTEXT_WINDOW = 6
_FACTUAL_INTENTS = {
    Intent.PRICE, Intent.COVERAGE, Intent.ELIGIBILITY, Intent.CLAIMS,
    Intent.WAITING_PERIOD, Intent.PAYMENT, Intent.APPLICATION, Intent.COMPARISON,
}


@dataclass
class AgentResult:
    reply: str
    opportunity: Opportunity
    detection: Detection
    retrieval: RetrievalResult
    score: ScoreCard
    state_change: str
    next_best_action: NextBestAction
    case: Optional[HumanCase] = None
    extraction_source: str = "rule"  # "llm" or "rule"


class SalesPilotAgent:
    def __init__(
        self,
        repository: Optional[Repository] = None,
        retriever: Optional[KnowledgeRetriever] = None,
        response_generator: Optional[ResponseGenerator] = None,
        llm_client=None,
    ) -> None:
        self.repo = repository or Repository()
        self.retriever = retriever or KnowledgeRetriever()
        self.response_generator = response_generator or ResponseGenerator()
        self.llm_extractor = LLMExtractor(llm_client) if llm_client else None
        # Rule-based fallback classifiers
        self.intent_classifier = IntentClassifier()
        self.product_classifier = ProductClassifier()
        self.signal_detector = SignalDetector()
        self.state_machine = OpportunityStateMachine()
        self.priority_engine = PriorityEngine()
        self.decision_engine = DecisionEngine()
        self.hitl = HITLManager()
        self.logger = setup_logging()

    def handle_message(
        self,
        customer_id: str,
        customer_name: str,
        text: str,
        client_message_id: Optional[str] = None,
    ) -> AgentResult:
        """Run the full pipeline for one customer message.

        `client_message_id` is recorded on the stored message for traceability
        and client-side reconciliation. Deduplication itself is handled one layer
        up, in the API endpoint, before this method is reached — by the time
        execution gets here the message is treated as new and `turns` advances
        (P0-5).
        """
        # 1) Context — load/create opportunity, append message
        opp = self._get_or_create(customer_id, customer_name)
        opp.turns += 1
        opp.messages.append(
            Message(role="customer", text=text, client_message_id=client_message_id)
        )
        context = opp.messages[-_CONTEXT_WINDOW:] if len(opp.messages) > 1 else None

        # 2) Intent & Context Understanding (LLM or rule-based extraction)
        extraction = self._extract(text, context)
        intent = extraction.intent
        product = extraction.product
        if product == Product.UNKNOWN:
            product = opp.product
        det = Detection(
            intent=intent,
            product=product,
            signals=extraction.signals,
            concerns=extraction.concerns,
            restricted=extraction.restricted,
        )

        # Whether a human had ALREADY taken over before this message. Once a
        # human owns the case, later customer messages must not move the
        # customer-facing state/score or resume autonomous sales — they are
        # only logged and used to accumulate observable signals (P0-3).
        #
        # Exception: EXPLICIT, customer-driven lifecycle transitions are still
        # allowed to move the opportunity even under takeover — they are the
        # customer's own actions, not autonomous AI sales. These are:
        #   - Withdrawal  ("I won't buy anymore")  -> Dormant/Lost
        #   - Conversion  ("I've signed up / paid") -> Closed/Active Customer
        # Human takeover REMAINS active in both cases; only the customer-facing
        # sales *decisions/response* stay suppressed (handled in the response
        # generator + NBA). Ambiguous / generic / hesitation messages are still
        # frozen so a stray message can't drag the opportunity back to a cold
        # lead while a human handles it.
        takeover_active = opp.human_takeover
        explicit_withdrawal = Signal.WITHDRAWAL in det.signals
        explicit_conversion = Signal.CONVERSION in det.signals
        lifecycle_transition = explicit_withdrawal or explicit_conversion
        freeze = takeover_active and not lifecycle_transition

        # 3) Opportunity State Detection
        old_state = opp.state
        transition = self.state_machine.transition(
            old_state, det, text, opp_signals=set(opp.signals)
        )
        if freeze:
            # Freeze the customer-facing state under human takeover. A later
            # generic / hesitation / postponement message must not drag the
            # opportunity back to Cold Lead or Dormant while a human handles it.
            opp.state = old_state
        else:
            opp.state = transition.new_state

            # Apply flag updates from the state machine
            if transition.set_churn_risk:
                opp.churn_risk = True
            if transition.set_expansion and transition.set_expansion not in opp.expansion:
                opp.expansion.append(transition.set_expansion)

        # 4) Sales Signal Detection — record in history, update active signals
        for signal in det.signals:
            if signal not in opp.signal_history:
                opp.signal_history.append(signal)

        # Withdrawal overrides active signals
        if Signal.WITHDRAWAL in det.signals:
            opp.signals = [Signal.WITHDRAWAL]
        else:
            # Accumulate active signals (don't duplicate)
            for signal in det.signals:
                if signal not in opp.signals:
                    opp.signals.append(signal)

        # 5) Update Opportunity Profile
        self._update_profile(opp, det, product, intent)

        # 6) Opportunity Value Score
        score = self.priority_engine.score(opp, det, text)
        # Under human takeover the score must not collapse because of a later
        # generic message — the opportunity's established value is preserved
        # for the human handling it (the profile is persistent memory).
        # Explicit lifecycle transitions (withdrawal / conversion) are exempt so
        # the score reflects the real outcome the human is working with.
        if freeze and opp.score is not None and score.total < opp.score.total:
            score = opp.score
        opp.score = score

        # 7) Priority is embedded in ScoreCard

        # 8) Next Best Action
        next_best_action = self.decision_engine.recommend(
            opp, det, escalated=False
        )

        # 9) Compliance / Permission Check (HITL)
        # RAG retrieval needed for confidence check in HITL
        retrieval = self.retriever.retrieve(text, product, intent)
        escalate_reason = self.hitl.evaluate(opp, det, retrieval, text)
        case: Optional[HumanCase] = None
        if escalate_reason:
            # One active case per opportunity — update existing or create new
            existing_case = self._find_active_case(opp.id)
            if existing_case:
                case = self.hitl.update_case(
                    existing_case, escalate_reason, opp, next_best_action.action
                )
                # `update_case` is part of BaseRepository (with a default
                # implementation), so every repository provides it — no
                # capability check needed.
                self.repo.update_case(case)
            else:
                case = self.hitl.create_case(opp, escalate_reason, next_best_action.action)
                self.repo.add_case(case)
                opp.human_takeover = True
                opp.human_intervention_required = True
            # Re-evaluate NBA with escalation flag
            next_best_action = self.decision_engine.recommend(
                opp, det, escalated=True
            )

        # P0-3: Once a human has taken over, the AI must not resume autonomous
        # customer-facing sales decisions on later messages — even when the
        # current message does not independently re-trigger HITL. Force the
        # next-best-action to "human handling" whenever takeover is active.
        if opp.human_takeover and not next_best_action.human_intervention_required:
            next_best_action = NextBestAction(
                action="Human take-over active: representative is handling the customer",
                reason="Human takeover is active — AI does not resume autonomous sales",
                priority=next_best_action.priority,
                human_intervention_required=True,
            )

        # 10) RAG Retrieval — already done in step 9 for confidence check
        # (retrieval variable is available for response generation)

        # 11) Answer / Nurture / Follow-up / Human Handoff
        reply = self.response_generator.generate(opp, det, retrieval, case, nba=next_best_action)
        opp.messages.append(Message(role="agent", text=reply))

        # 12) Save Decision + Score History
        opp.score_history.append(ScoreHistoryEntry(
            timestamp=datetime.now(),
            score=score.total,
            state=opp.state.value,
            trigger=f"message({extraction.source})",
        ))
        if old_state != opp.state:
            opp.state_history.append(StateHistoryEntry(
                timestamp=datetime.now(),
                from_state=old_state.value,
                to_state=opp.state.value,
                reason=transition.reason,
            ))

        self.repo.upsert_opportunity(opp)
        self._log_event(
            opp, det, retrieval, old_state.value, opp.state.value,
            transition.reason, next_best_action, case,
        )

        return AgentResult(
            reply=reply,
            opportunity=opp,
            detection=det,
            retrieval=retrieval,
            score=score,
            state_change=f"{old_state.value} -> {opp.state.value} ({transition.reason})",
            next_best_action=next_best_action,
            case=case,
            extraction_source=extraction.source,
        )

    def _extract(self, text: str, context) -> ExtractionResult:
        """Use LLM extractor if available, otherwise rule-based."""
        if self.llm_extractor:
            return self.llm_extractor.extract(text, context=context)
        # Rule-based fallback
        intent = self.intent_classifier.detect(text, context=context)
        product = self.product_classifier.detect(text, context=context)
        det = self.signal_detector.detect(text, intent, product, context=context)
        return ExtractionResult(
            intent=intent,
            product=product,
            signals=det.signals,
            concerns=det.concerns,
            restricted=det.restricted,
            source="rule",
        )

    # ---- Internals -------------------------------------------------------

    def _find_active_case(self, opportunity_id: str) -> Optional[HumanCase]:
        """Find an OPEN or TAKEN_OVER case for this opportunity."""
        for case in self.repo.list_cases():
            if case.opportunity_id == opportunity_id and case.status != CaseStatus.CLOSED:
                return case
        return None

    def _get_or_create(self, customer_id: str, customer_name: str) -> Opportunity:
        opp = self.repo.get_opportunity(customer_id)
        if opp is None:
            opp = Opportunity(
                id=customer_id or f"C-{uuid.uuid4().hex[:6].upper()}",
                customer_name=customer_name,
            )
        return opp

    @staticmethod
    def _update_profile(
        opp: Opportunity,
        det: Detection,
        product: Product,
        intent,
    ) -> None:
        from ..engine.scoring import PriorityEngine

        opp.product = product
        opp.last_intent = intent
        # Maintain the strongest buying intent seen so far (persistent memory).
        # A later generic message must not erase established purchase intent.
        if PriorityEngine.intent_strength(intent) >= PriorityEngine.intent_strength(
            opp.best_intent
        ):
            opp.best_intent = intent
        if det.concerns:
            opp.main_concern = det.concerns[-1]
        if Signal.COMPETITIVE in det.signals:
            opp.competitive_risk = True
        if Signal.COMPLIANCE_RISK in det.signals:
            opp.compliance_risk = True
        if Signal.EXPANSION_FAMILY in det.signals and "Family" not in opp.expansion:
            opp.expansion.append("Family")
        if Signal.EXPANSION_CORPORATE in det.signals and "Corporate" not in opp.expansion:
            opp.expansion.append("Corporate")

    def _log_event(
        self, opp, det, retrieval, old_state, new_state,
        state_reason, nba: NextBestAction, case,
    ) -> None:
        self.logger.info(
            "event | customer=%s(%s) | intent=%s product=%s signals=[%s] | "
            "state=%s->%s (%s) | confidence=%.2f | score=%s priority=%s | "
            "nba=%s human=%s | case=%s",
            opp.customer_name,
            opp.id,
            det.intent.value,
            opp.product.value,
            ",".join(s.value for s in det.signals) or "-",
            old_state,
            new_state,
            state_reason,
            retrieval.confidence,
            opp.score.total,
            opp.score.priority.value,
            nba.action,
            nba.human_intervention_required,
            case.id if case else "-",
        )
