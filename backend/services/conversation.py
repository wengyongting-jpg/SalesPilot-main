# -*- coding: utf-8 -*-
"""One customer message, end to end — `docs/backend-plan.md` §3.

    1. observing segment    agent.extraction  → Detection, HandoffProposal
    2. kernel               plain Python, mandatory, exactly once, fixed order:
                            takeover → qualification → state_transition →
                            profile → scoring (priority) → retrieval → hitl →
                            next_best_action
    3. composing segment    agent.reply, given only a customer-safe projection
    4. storage + observability

The kernel is a sequence of calls in this file, not a tool the model may
skip. Offline and online differ only in which extractor and composer are
plugged in; the decision path is byte-identical.

Idempotency: a replayed `client_message_id` for the same conversation
returns the stored receipt verbatim and touches nothing — not the transcript,
not the counters, not the histories (`backend-contract.md` item 1).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional

from .. import config
from ..agent import policy, runtime
from ..agent.extraction import Extractor, build_extractor
from ..agent.reply import Composer, build_composer
from ..domain.case import HumanCase
from ..domain.detection import Detection, RetrievalResult
from ..domain.enums import Intent, OpportunityState, Product, Signal
from ..domain.message import Message
from ..domain.opportunity import (
    Opportunity,
    ScoreCard,
    ScoreHistoryEntry,
    StateHistoryEntry,
)
from ..kernel import (
    hitl,
    next_best_action,
    qualification,
    quick_replies,
    scoring,
    state_machine,
    takeover,
)
from ..kernel.next_best_action import NextBestAction
from ..kernel.quick_replies import QuickReply
from ..knowledge.retriever import KnowledgeRetriever
from ..observability import AgentRun, RunRecorder, print_run
from ..observability.logging import log_run
from ..storage.base import Repository
from . import cases

# §12.1: model-authored free text is a prompt-injection path; keep it short.
_MAX_CONCERN_CHARS = 200


@dataclass
class TurnResult:
    opportunity: Opportunity
    reply: Message
    receipt: dict[str, Any]
    replayed: bool = False
    # Present only when the pipeline actually ran this turn.
    detection: Optional[Detection] = None
    retrieval: Optional[RetrievalResult] = None
    score: Optional[ScoreCard] = None
    state_change: Optional[str] = None
    next_best_action: Optional[NextBestAction] = None
    case: Optional[HumanCase] = None
    quick_replies: list[QuickReply] = field(default_factory=list)
    run: Optional[AgentRun] = None
    extraction_source: Optional[str] = None


class ConversationService:
    def __init__(
        self,
        repo: Repository,
        *,
        extractor: Extractor,
        composer: Composer,
        retriever: Optional[KnowledgeRetriever] = None,
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.repo = repo
        self.extractor = extractor
        self.composer = composer
        self.retriever = retriever or KnowledgeRetriever()
        self._now = now

    # ---- The use-case -----------------------------------------------------------

    def handle_customer_message(
        self,
        customer_id: str,
        customer_name: str,
        text: str,
        *,
        client_message_id: Optional[str] = None,
    ) -> TurnResult:
        key = (client_message_id or "").strip() or None
        scope = (customer_id or "").strip()

        if key and scope:
            stored = self.repo.get_receipt(scope, key)
            if stored is not None:
                opp = self.repo.get_opportunity(scope)
                return TurnResult(opportunity=opp, reply=_reply_from_receipt(stored), receipt=stored, replayed=True)

        opp = self._get_or_create(scope, customer_name)
        now = self._now()
        opp.customer_message_count += 1
        opp.messages.append(Message.from_customer(text, client_message_id=key, ts=now))
        context = opp.messages[:-1] or None
        old_state = opp.state

        recorder = RunRecorder(
            opp.id,
            client_message_id=key,
            customer_message_count=opp.customer_message_count,
        )

        # 1. Observing segment.
        outcome = self.extractor.extract(text, context, recorder=recorder)
        det = outcome.detection
        if det.product is Product.UNKNOWN:
            det.product = opp.product  # product is sticky across the conversation

        # 2. Kernel, in the mandated order.
        with recorder.step("takeover", "rule") as step:
            decision = takeover.evaluate(opp, det)
            step.note(decision.reason)

        with recorder.step("qualification", "rule") as step:
            # `assess` reads `opp.solicitation_count` as the count *before*
            # this message and adds one itself for a soliciting current
            # message (see its "two strikes" doctring) — incrementing here
            # first double-counted the current message against its own
            # two-strike requirement, holding a conversation on a single
            # soliciting message instead of two. The increment must persist
            # only after the verdict is read.
            verdict = qualification.assess(opp, det)
            if det.solicitation:
                opp.solicitation_count += 1
            opp.qualification = verdict.level
            opp.qualification_reason = verdict.reason
            step.note(verdict.reason or verdict.level.value)

        with recorder.step("state_transition", "rule") as step:
            transition = state_machine.transition(opp.state, det, accumulated_signals=set(opp.signals))
            if decision.freeze_state:
                step.note(f"{old_state.value} (frozen: {decision.reason})")
            else:
                opp.state = transition.new_state
                if transition.set_churn_risk:
                    opp.churn_risk = True
                if transition.set_expansion and transition.set_expansion not in opp.expansion:
                    opp.expansion.append(transition.set_expansion)
                step.note(
                    f"{old_state.value} -> {opp.state.value}"
                    if transition.moved
                    else f"{opp.state.value} (unchanged)"
                )

        with recorder.step("profile_update", "rule") as step:
            _update_profile(opp, det, text)
            step.note(f"intent={det.intent.value} best={opp.best_intent.value} signals={len(opp.signals)}")

        with recorder.step("scoring", "rule") as step:
            card = scoring.score(opp, det, text, now=now)
            if decision.preserve_score_floor and opp.score is not None and card.total < opp.score.total:
                card = opp.score
            opp.score = card
            step.note(f"{card.total} {card.priority.value}")

        with recorder.step("knowledge_retrieval", "retrieval") as step:
            mentioned = (
                self.retriever.detect_mentioned_products(text)
                if det.intent is Intent.COMPARISON
                else []
            )
            if len(mentioned) >= 2:
                retrieval = self.retriever.retrieve_comparison(mentioned[0], mentioned[1])
            else:
                retrieval = self.retriever.retrieve(text, opp.product, det.intent)
            step.note(f"confidence={retrieval.confidence:.2f} facts={len(retrieval.facts)}")

        with recorder.step("hitl", "rule") as step:
            proposal = outcome.handoff
            proposal_accepted = proposal is not None and hitl.accepts_proposal(opp, det, proposal)
            reason = hitl.evaluate(
                opp,
                det,
                retrieval,
                confidence_floor=config.RETRIEVAL_CONFIDENCE_ESCALATE,
                proposal=proposal,
            )
            case: Optional[HumanCase] = None
            if reason:
                nba_for_case = next_best_action.recommend(opp, det, escalated=True)
                case, _created = cases.open_or_update_case(
                    self.repo, opp, reason=reason, recommended_action=nba_for_case.action
                )
                opp.human_takeover = True
                opp.human_intervention_required = True
            detail = f"escalate={reason}" if reason else "no escalation"
            if proposal is not None and proposal.requested:
                detail += f"; proposal={proposal.reason!r} -> {'accepted' if proposal_accepted else 'declined'}"
            step.note(detail)

        with recorder.step("next_best_action", "rule") as step:
            nba = next_best_action.recommend(opp, det, escalated=bool(reason))
            step.note(nba.action)

        chips = quick_replies.suggest(opp, det)

        # 3. Composing segment: only a customer-safe projection crosses over.
        withdrawal = Signal.WITHDRAWAL in det.signals
        escalate = bool(reason)
        was_under_takeover = decision.active
        # First contact, nothing specific asked yet: a greeting, not a
        # request for the full catalogue. Scoped to the first message only,
        # matching the frozen build's `_GENERIC_HELP` case — a later bare
        # "hi" is an ordinary customer message and gets an ordinary answer.
        greeting = det.intent is Intent.GENERIC and opp.customer_message_count <= 1
        instruction = policy.customer_safe_projection(
            escalate=escalate,
            withdrawal=withdrawal,
            takeover=was_under_takeover,
            greeting=greeting,
            hesitation=Signal.HESITATION in det.signals,
            high_intent=opp.state is OpportunityState.HIGH_INTENT,
        )
        reply = self.composer.compose(
            instruction,
            retrieval,
            withdrawal=withdrawal,
            takeover=was_under_takeover,
            escalate=escalate,
            greeting=greeting,
            recorder=recorder,
            customer_message=text,
        )
        opp.messages.append(reply)

        # 4. Storage and observability.
        opp.score_history.append(
            ScoreHistoryEntry(now, card.total, opp.state.value, trigger=f"message({outcome.source})")
        )
        state_change = None
        if old_state is not opp.state:
            opp.state_history.append(StateHistoryEntry(now, old_state.value, opp.state.value, transition.reason))
            state_change = f"{old_state.value} -> {opp.state.value} ({transition.reason})"
        self.repo.upsert_opportunity(opp)

        run = recorder.finish()
        self.repo.save_run(run.to_dict(include_content=config.TELEMETRY_CONTENT))
        print_run(run)
        log_run(run)

        receipt = {
            "opportunity_id": opp.id,
            "client_message_id": key,
            "reply": reply.text,
            "generation": reply.generation_value,
            "product": opp.product.value,
            "facts": list(retrieval.facts),
            "quick_replies": [{"id": c.id, "label": c.label} for c in chips],
            "human_takeover": opp.human_takeover,
            "state_change": state_change,
            "score_total": card.total,
            "run_id": run.run_id,
        }
        if key:
            self.repo.save_receipt(opp.id, key, receipt)

        return TurnResult(
            opportunity=opp,
            reply=reply,
            receipt=receipt,
            detection=det,
            retrieval=retrieval,
            score=card,
            state_change=state_change,
            next_best_action=nba,
            case=case,
            quick_replies=chips,
            run=run,
            extraction_source=outcome.source,
        )

    # ---- Internals ----------------------------------------------------------------

    def _get_or_create(self, customer_id: str, customer_name: str) -> Opportunity:
        if customer_id:
            existing = self.repo.get_opportunity(customer_id)
            if existing is not None:
                return existing
        return Opportunity(id=customer_id or f"C-{uuid.uuid4().hex[:6].upper()}", customer_name=customer_name)


def build_service(repo: Repository, **overrides: Any) -> ConversationService:
    """Wire the configured model (or none) into both peers. The one place that decides."""
    model = runtime.build_model()
    return ConversationService(
        repo,
        extractor=overrides.pop("extractor", None) or build_extractor(model),
        composer=overrides.pop("composer", None) or build_composer(model),
        **overrides,
    )


# ---- Helpers --------------------------------------------------------------------


def _update_profile(opp: Opportunity, det: Detection, text: str) -> None:
    for signal in det.signals:
        if signal not in opp.signal_history:
            opp.signal_history.append(signal)
    if Signal.WITHDRAWAL in det.signals:
        opp.signals = [Signal.WITHDRAWAL]
    else:
        # A prior withdrawal is per-turn, not permanent: the reply-mode
        # decision above already only looks at *this* turn's signals, so a
        # customer who re-engages gets an ordinary answer — but without this,
        # the stale flag stayed in `opp.signals` forever, silently
        # suppressing quick replies and the next-best-action recommendation
        # on every later turn even after the customer had moved on.
        if Signal.WITHDRAWAL in opp.signals:
            opp.signals = [s for s in opp.signals if s is not Signal.WITHDRAWAL]
        for signal in det.signals:
            if signal not in opp.signals:
                opp.signals.append(signal)

    opp.product = det.product
    opp.last_intent = det.intent
    opp.best_intent = scoring.effective_intent(det.intent, opp.best_intent)
    if scoring.urgency_in(text):
        opp.urgency_observed = True
    if det.concerns:
        opp.main_concern = det.concerns[-1][:_MAX_CONCERN_CHARS]
    if Signal.COMPETITIVE in det.signals:
        opp.competitive_risk = True
    if Signal.COMPLIANCE_RISK in det.signals:
        opp.compliance_risk = True
    if Signal.EXPANSION_FAMILY in det.signals and "Family" not in opp.expansion:
        opp.expansion.append("Family")
    if Signal.EXPANSION_CORPORATE in det.signals and "Corporate" not in opp.expansion:
        opp.expansion.append("Corporate")


def _reply_from_receipt(receipt: dict[str, Any]) -> Message:
    return Message.from_ai(receipt["reply"], generation=receipt.get("generation") or "template")
