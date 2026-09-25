# -*- coding: utf-8 -*-
"""One customer message, end to end — `docs/v0.0/backend/backend-plan.md` §3.

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
from ..agent.model_factory import build as build_model
from ..agent.reply import Composer, build_composer
from ..domain.case import HumanCase
from ..domain.detection import Detection, RetrievalResult
from ..domain.enums import Generation, Intent, OpportunityState, Product, ReplyMode, Signal
from ..domain.message import Message, MessageAuthor, MessageRole
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

# The reply and the cards must agree: returning a premium fact alongside "a
# representative will be in touch" would put a price card under a handover
# message, or offer plans to a conversation the qualification gate has held.
# `retrieval.facts` still runs in every mode (so telemetry sees what would
# have been available), but only these three modes are permitted to *show*
# them to the customer.
_NO_FACTS_REPLY_MODES = frozenset(
    {ReplyMode.HANDOVER, ReplyMode.HOLD, ReplyMode.WITHDRAWN, ReplyMode.GREETING}
)


class QuestionAnswerTooLong(ValueError):
    """A free-form answer exceeded the approved customer question limit."""


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
    # What the assistant was permitted to say this turn — not `retrieval.facts`
    # directly, which still runs in every mode. Empty whenever the reply mode
    # is one the customer-safe reply must not attach a product card to.
    customer_facts: list[str] = field(default_factory=list)
    # Set once, on the turn that actually ran the pipeline, and copied onto a
    # replay's `TurnResult` verbatim: idempotency means a replay returns the
    # exact original response, not a best-effort reconstruction from whatever
    # the narrow receipt happened to keep. `replayed` is deliberately not a
    # key inside this dict — it is a fact about *this call*, asserted
    # separately on `TurnResult.replayed`, not about the response content
    # two calls must agree on.
    _snapshot: Optional[dict[str, Any]] = field(default=None, repr=False)

    def to_dict(self) -> dict[str, Any]:
        """Serialize for testing and API responses."""
        if self._snapshot is not None:
            return self._snapshot

        from ..services.serialisation import (
            action_to_dict,
            case_to_dict,
            detection_to_dict,
            message_to_dict,
            opportunity_to_dict,
            retrieval_to_dict,
        )

        return {
            "opportunity_id": self.opportunity.id,
            "opportunity": opportunity_to_dict(self.opportunity),
            "reply": self.reply.text,
            "message": message_to_dict(self.reply),
            "generation": self.reply.generation.value if self.reply.generation else None,
            "detection": detection_to_dict(self.detection),
            "retrieval": retrieval_to_dict(self.retrieval),
            "next_best_action": action_to_dict(self.next_best_action),
            "case": case_to_dict(self.case),
            "agent_run": self.run.to_dict(include_content=False) if self.run else None,
            "quick_replies": [{"id": c.id, "label": c.label} for c in self.quick_replies],
            "customer_facts": list(self.customer_facts),
            "state_change": self.state_change,
            "score_total": self.score.total if self.score else None,
            "client_message_id": self.receipt.get("client_message_id"),
            "extraction_source": self.extraction_source,
        }


class ConversationService:
    def __init__(
        self,
        repo: Repository,
        *,
        extractor: Optional[Extractor] = None,
        composer: Optional[Composer] = None,
        model: Any = None,
        trace: Optional[bool] = None,
        retriever: Optional[KnowledgeRetriever] = None,
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        # `model=` is a convenience for callers (e.g. `backend.evals`) that want
        # both peers built from one provider without wiring `build_extractor`/
        # `build_composer` themselves. An explicit `extractor=`/`composer=`
        # always wins, so `build_service`'s own wiring is unaffected.
        self.repo = repo
        self.extractor = extractor or build_extractor(model)
        self.composer = composer or build_composer(model)
        self.retriever = retriever or KnowledgeRetriever()
        self._now = now
        if trace is not None:
            config.CONSOLE_TRACE = trace

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
                # Find the actual reply message from the conversation history
                # The reply message should be right after the customer message with this key
                reply_msg = None
                for i, msg in enumerate(opp.messages):
                    if msg.role == MessageRole.CUSTOMER and msg.client_message_id == key:
                        # The next message should be the AI reply
                        if i + 1 < len(opp.messages):
                            reply_msg = opp.messages[i + 1]
                        break
                # Fallback to creating from receipt if not found
                if reply_msg is None:
                    reply_msg = _reply_from_receipt(stored)

                # Reconstruct quick_replies from receipt
                chips_from_receipt = [
                    QuickReply(id=c["id"], label=c["label"])
                    for c in stored.get("quick_replies", [])
                ]

                # Reconstruct retrieval with facts from receipt
                from ..domain.detection import RetrievalResult
                retrieval = RetrievalResult(facts=stored.get("facts", []))

                replay = TurnResult(
                    opportunity=opp,
                    reply=reply_msg,
                    receipt=stored,
                    quick_replies=chips_from_receipt,
                    retrieval=retrieval,
                    replayed=True,
                )
                # A receipt saved before this snapshot mechanism existed has
                # no `_snapshot`; the fields reconstructed above are the
                # fallback for that case.
                snapshot = stored.get("_snapshot")
                if snapshot is not None:
                    replay._snapshot = snapshot
                return replay

        opp = self._get_or_create(scope, customer_name)
        now = self._now()
        opp.customer_message_count += 1
        opp.messages.append(Message.from_customer(text, client_message_id=key, ts=now))

        recorder = RunRecorder(
            opp.id,
            client_message_id=key,
            customer_message_count=opp.customer_message_count,
        )

        # Check for pending handoff confirmation
        if opp.pending_handoff_reason:
            answer = self._handoff_answer(text)
            if answer is not None:
                # Customer answered Confirm/Cancel
                return self._resolve_handoff(opp, answer, client_message_id=key, recorder=recorder)
            # Other response supersedes the handoff offer; evaluate it afresh
            with recorder.step("handoff_superseded", "rule") as step:
                step.note(f"Customer response '{text[:50]}' supersedes pending handoff; evaluating as new request")
            opp.pending_handoff_reason = None

        context = opp.messages[:-1] or None
        old_state = opp.state

        # 1. Observing segment.
        history_search = lambda query, limit: self.repo.search_messages(
            opp.id, query, limit=limit
        )
        outcome = self.extractor.extract(
            text,
            context,
            recorder=recorder,
            memory=self.repo.get_memory(opp.id),
            opportunity_id=opp.id,
            history_search=history_search,
            opportunity=opp,
        )
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
            # `evaluate` decides proposal acceptance internally (qualification,
            # takeover) and returns it encoded in `reason` itself — there is no
            # separate acceptance function to call. `proposal_accepted` here is
            # only for the diagnostic note below, derived from that same
            # returned reason rather than duplicating the acceptance check.
            reason = hitl.evaluate(
                opp,
                det,
                retrieval,
                confidence_floor=config.RETRIEVAL_CONFIDENCE_ESCALATE,
                customer_text=text,
                proposal=proposal,
            )
            proposal_accepted = bool(reason) and reason.startswith(hitl.REASON_ASSISTANT_PROPOSED)
            case: Optional[HumanCase] = None
            if reason:
                # Instead of creating case directly, set pending for confirmation
                existing_case = self.repo.active_case_for(opp.id)
                if existing_case is not None:
                    # Already have an active case: update it
                    nba_for_case = next_best_action.recommend(opp, det, escalated=True)
                    existing_case.reason = reason
                    existing_case.state = opp.state
                    existing_case.recommended_action = nba_for_case.action
                    existing_case.summary = f"{existing_case.summary} [Update] {reason}"
                    case = existing_case
                    opp.human_takeover = True
                    opp.human_intervention_required = True
                else:
                    # No active case: request confirmation first
                    step.note(f"confirmation requested: {reason}")
                    opp.pending_handoff_reason = reason
                    opp.human_intervention_required = True
            detail = f"escalate={reason}" if reason else "no escalation"
            if proposal is not None and proposal.requested:
                detail += f"; proposal={proposal.reason!r} -> {'accepted' if proposal_accepted else 'declined'}"
            step.note(detail)

        with recorder.step("next_best_action", "rule") as step:
            nba = next_best_action.recommend(opp, det, escalated=bool(reason))
            step.note(nba.action)

        chips = quick_replies.suggest(opp, det)
        customer_facts = [] if nba.reply_mode in _NO_FACTS_REPLY_MODES else list(retrieval.facts)

        # 3. Composing segment: only a customer-safe projection crosses over.
        withdrawal = Signal.WITHDRAWAL in det.signals
        escalate = bool(reason)
        was_under_takeover = decision.active

        # Check if we need to request handoff confirmation
        if opp.pending_handoff_reason:
            # Return confirmation prompt instead of normal reply
            handoff_reason = opp.pending_handoff_reason
            if handoff_reason == hitl.REASON_HUMAN_REQUEST:
                prompt = "Would you like me to notify a CareSure representative?"
            elif handoff_reason == hitl.REASON_COMPETITIVE:
                prompt = "A representative can help with the next step. Shall I notify the team?"
            else:
                prompt = "That needs a representative's review; I cannot decide it here. Shall I notify the team?"

            reply_text = f"{prompt} Reply 'Confirm' or 'Cancel'."
            reply_message = Message(
                role=MessageRole.BUSINESS,
                text=reply_text,
                author=MessageAuthor.AI,
                generation=Generation.TEMPLATE,
            )
            opp.messages.append(reply_message)
            chips = self._handoff_chips()

            with recorder.step("response_generation", "template") as step:
                step.note(f"handoff_confirmation_requested reason={handoff_reason}")
        else:
            # Normal reply generation.
            # Build ReplyRequest from the kernel decision
            from ..agent.reply import ReplyRequest
            from ..knowledge import loader
            kb = loader.load()
            reply_request = ReplyRequest(
                action=nba,
                facts=list(retrieval.facts),
                customer_name=opp.customer_name,
                concern=opp.main_concern,
                disclaimer=kb.disclaimer,
                history=opp.messages[:-1],  # All messages except the current customer message
                # `retrieval.product` is UNKNOWN only for the product-overview
                # case (`KnowledgeRetriever._product_overview`) - a short,
                # already-curated one-liner per plan, not a larger pool to pick
                # 1-2 fields from. Selecting *among* products there answers a
                # different question than "what plans are there".
                select_facts=retrieval.product is not Product.UNKNOWN,
            )

            # 3. Composing segment: record as response_generation step
            with recorder.step("response_generation", "template") as step:
                reply_outcome = self.composer.compose(reply_request)
                step.note(f"mode={nba.reply_mode.value} facts={len(reply_request.facts)}")
                if reply_outcome.degraded and not reply_outcome.by_design:
                    step.degrade(reply_outcome.degradation_reason or "degraded")

            reply_message = Message(
                role=MessageRole.BUSINESS,
                text=reply_outcome.text,
                author=MessageAuthor.AI,
                generation=reply_outcome.generation,
            )
            opp.messages.append(reply_message)

        # 4. Storage and observability.
        opp.score_history.append(
            ScoreHistoryEntry(now, card.total, opp.state.value, trigger=f"message({outcome.source})")
        )
        state_change = None
        if old_state is not opp.state:
            opp.state_history.append(StateHistoryEntry(now, old_state.value, opp.state.value, transition.reason))
            state_change = f"{old_state.value} -> {opp.state.value} ({transition.reason})"
        run = recorder.finish()
        run_payload = run.to_dict(include_content=config.TELEMETRY_CONTENT)

        receipt = {
            "opportunity_id": opp.id,
            "client_message_id": key,
            "reply": reply_message.text,
            "generation": reply_message.generation.value,
            "product": opp.product.value,
            "facts": customer_facts,
            "quick_replies": [{"id": c.id, "label": c.label} for c in chips],
            "human_takeover": opp.human_takeover,
            "state_change": state_change,
            "score_total": card.total,
            "run_id": run.run_id,
        }

        result = TurnResult(
            opportunity=opp,
            reply=reply_message,
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
            customer_facts=customer_facts,
        )
        if key:
            # Freeze the exact response now, before it is returned, so a
            # replay of this same key later returns this precise snapshot
            # rather than a reconstruction from the narrower receipt fields.
            result._snapshot = result.to_dict()
            receipt["_snapshot"] = result._snapshot
        self.repo.save_turn(
            opp,
            run_payload,
            case=case,
            receipt=receipt if key else None,
            memory=outcome.memory,
        )
        print_run(run)
        log_run(run)
        return result

    def reset(self, conversation_id: str) -> bool:
        """Discard a conversation. Returns whether there was one.

        Here rather than in the route handler because `services` is the only package
        that writes storage — concentrating the writes is what makes the transaction
        boundary and the idempotency check meaningful, and a write from a route would
        bypass both. The architecture test caught this when the first version of the
        reset endpoint called the repository directly.
        """
        existed = self.repo.get_opportunity(conversation_id, history_limit=0) is not None
        self.repo.delete_opportunity(conversation_id)
        return existed

    # ---- Internals ----------------------------------------------------------------

    def _get_or_create(self, customer_id: str, customer_name: str) -> Opportunity:
        if customer_id:
            existing = self.repo.get_opportunity(customer_id)
            if existing is not None:
                return existing
        return Opportunity(id=customer_id or f"C-{uuid.uuid4().hex[:6].upper()}", customer_name=customer_name)

    @staticmethod
    def _handoff_chips() -> list[QuickReply]:
        """Quick reply buttons for handoff confirmation."""
        return [
            QuickReply(id="handoff_confirm", label="Confirm"),
            QuickReply(id="handoff_cancel", label="Cancel"),
        ]

    @staticmethod
    def _handoff_answer(text: str) -> Optional[bool]:
        """Parse customer's handoff confirmation response.

        Returns True for confirmation, False for cancellation, None for other responses.
        """
        normalized = " ".join(text.lower().split()).strip(".!? ")
        if normalized in {"confirm", "yes", "yes please", "please do", "确认", "是", "好的"}:
            return True
        if normalized in {"cancel", "no", "no thanks", "not now", "取消", "否", "不用"}:
            return False
        return None

    def _resolve_handoff(
        self,
        opp: Opportunity,
        confirmed: bool,
        *,
        client_message_id: Optional[str],
        recorder: RunRecorder,
    ) -> TurnResult:
        """Process customer's handoff confirmation decision."""
        reason = opp.pending_handoff_reason or "Customer requested a representative"
        opp.pending_handoff_reason = None
        case = None
        now = self._now()

        if confirmed:
            # Customer confirmed: create the case
            case = self.repo.active_case_for(opp.id)
            if case is None:
                case = HumanCase(
                    opportunity_id=opp.id,
                    customer_name=opp.customer_name,
                    state=opp.state,
                    product=opp.product,
                    reason=reason,
                    recommended_action="Contact representative",
                    summary=f"{opp.customer_name} confirmed handoff: {reason}",
                )
            else:
                # Update existing case
                case.reason = reason
                case.state = opp.state
                case.recommended_action = "Contact representative"
                case.summary = f"{case.summary} [Update] Customer confirmed: {reason}"

            opp.human_takeover = True
            reply_text = "A representative will contact you shortly. Thank you for your patience."
        else:
            # Customer cancelled: continue with AI
            reply_text = "Understood. How else can I help you?"

        reply_message = Message(
            ts=now,
            role=MessageRole.BUSINESS,
            text=reply_text,
            author=MessageAuthor.AI,
            generation=Generation.TEMPLATE,
        )
        opp.messages.append(reply_message)

        run = recorder.finish()
        run_payload = run.to_dict(include_content=config.TELEMETRY_CONTENT)

        receipt = {
            "opportunity_id": opp.id,
            "client_message_id": client_message_id,
            "reply": reply_text,
            "generation": Generation.TEMPLATE.value,
            "product": opp.product.value,
            "facts": [],
            "quick_replies": [],
            "human_takeover": opp.human_takeover,
            "state_change": None,
            "score_total": opp.score.total if opp.score else 0,
            "run_id": run.run_id,
        }
        self.repo.save_turn(
            opp,
            run_payload,
            case=case,
            receipt=receipt if client_message_id else None,
        )

        return TurnResult(
            opportunity=opp,
            reply=reply_message,
            receipt=receipt,
            case=case,
            quick_replies=[],
            run=run,
        )


def build_service(repo: Repository, **overrides: Any) -> ConversationService:
    """Wire the configured model (or none) into both peers. The one place that decides."""
    built = build_model()
    return ConversationService(
        repo,
        extractor=overrides.pop("extractor", None) or build_extractor(built.model),
        composer=overrides.pop("composer", None) or build_composer(built.model),
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
