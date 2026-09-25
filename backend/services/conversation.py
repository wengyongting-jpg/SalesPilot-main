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

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional

from .. import config
from ..agent import policy, runtime
from ..agent import telemetry
from ..agent.budget import for_turn as model_budget_for_turn
from ..agent.extraction import Extractor, build_extractor
from ..agent.extraction.rules import product as product_rules
from ..agent.model_factory import build as build_model
from ..agent.reply import Composer, build_composer
from ..domain.case import HumanCase
from ..domain.decision import (
    ActionKind, ActionStatus, Decision, DecisionAction, PendingAction,
)
from ..domain.detection import (
    BuyingPosture, Detection, EvidenceQuality, RetrievalResult, TransactionIssue,
)
from ..domain.enums import CaseStatus, Generation, Intent, OpportunityState, Product, ReplyMode, Signal
from ..domain.message import Message, MessageAuthor, MessageRole
from ..domain.opportunity import (
    Opportunity,
    ScoreCard,
    ScoreHistoryEntry,
    StateHistoryEntry,
)
from ..kernel import (
    decision as decision_policy,
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
from ..knowledge import questions
from ..knowledge.retriever import PRODUCT_SURVEY_INTENTS, KnowledgeRetriever
from ..observability import AgentRun, RunRecorder, print_run
from ..observability.logging import log_run
from ..storage.base import Repository
from . import cases

# §12.1: model-authored free text is a prompt-injection path; keep it short.
_MAX_CONCERN_CHARS = 200

# Retrieval still runs in every mode for diagnostics, but these modes do not
# show facts. The composer reports which facts it actually rendered; retrieval
# alone must never be used to populate customer-facing cards.
_NO_FACTS_REPLY_MODES = frozenset(
    {ReplyMode.HANDOVER, ReplyMode.HOLD, ReplyMode.WITHDRAWN, ReplyMode.GREETING}
)

# Matches `questions.normalise_answer`'s own truncation, so a customer is told
# their answer is too long rather than having it silently cut off mid-word.
_MAX_QUESTION_ANSWER_CHARS = 200

# A corporate customer who already states a headcount ("we have 200
# employees") has answered before being asked; this is checked against the
# customer's own text, not by product/intent alone, the same way the other
# text-level checks in this pipeline are (the catalogue-request check, the
# corporate-quote regex).
_EMPLOYEE_COUNT_MENTION = re.compile(
    r"\b\d{1,4}\s*(?:employees?|staff|headcount|people|workers)\b", re.IGNORECASE
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
    # Approved facts actually rendered this turn, not all retrieved candidates.
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
            "customer_question": (
                questions.payload(self.opportunity.pending_question_field)
                if self.opportunity.pending_question_field else None
            ),
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

        # Resolve short responses only against an explicit typed prompt.
        pending = opp.pending_action
        if pending is None and opp.pending_handoff_reason:
            # Lazy compatibility for in-memory records written before typed actions.
            pending = PendingAction(
                kind=ActionKind.HANDOFF, reason_code="legacy_handoff",
                reason=opp.pending_handoff_reason,
                originating_customer_message_id=None,
                originating_assistant_message_id=None,
                status=ActionStatus.PENDING, created_at=now,
            )
            opp.pending_action = pending
        pending_decision = decision_policy.decide_pending_response(
            pending, text, current_message_id=opp.messages[-1].id,
        )
        requested_handoff_reason = None
        cancelled_readiness_invitation = False
        clarify_unanchored_affirmative = bool(
            (pending is None or pending.status is not ActionStatus.PENDING)
            and pending_decision is not None
            and pending_decision.action is DecisionAction.CLARIFY
        )
        clarify_ready_without_referent = False
        if pending_decision is not None:
            if pending_decision.action is DecisionAction.CONFIRM_HANDOFF:
                return self._resolve_handoff(opp, True, client_message_id=key, recorder=recorder)
            if pending_decision.action is DecisionAction.CANCEL_HANDOFF:
                if pending and pending.kind is ActionKind.HANDOFF:
                    return self._resolve_handoff(opp, False, client_message_id=key, recorder=recorder)
                cancelled_readiness_invitation = bool(
                    pending and pending.kind is ActionKind.READINESS_INVITATION
                )
                pending.status = ActionStatus.CANCELLED
                opp.pending_handoff_reason = None
            elif pending_decision.action is DecisionAction.OFFER_HANDOFF:
                requested_handoff_reason = hitl.REASON_READY_TO_PROCEED
                pending.status = ActionStatus.CONFIRMED
            elif pending_decision.action is DecisionAction.CLARIFY:
                pass
            else:
                with recorder.step("pending_action_superseded", "rule") as step:
                    step.note("Pending prompt response was unrelated; evaluating as a new request")
                pending.status = ActionStatus.CANCELLED
                opp.pending_handoff_reason = None

        # Check for a pending clarifying-question answer. Captured, then still
        # falls through into normal extraction below with the same text: an
        # answer like "we have 200 employees" is also worth extracting for its
        # own signals, not only as this question's answer.
        if opp.pending_question_field:
            field = opp.pending_question_field
            if len(text.strip()) > _MAX_QUESTION_ANSWER_CHARS:
                raise QuestionAnswerTooLong(
                    f"Answer to the pending question must be "
                    f"{_MAX_QUESTION_ANSWER_CHARS} characters or fewer."
                )
            with recorder.step("question_answered", "rule") as step:
                answer = questions.normalise_answer(field, text)
                if answer is not None:
                    opp.collected_answers[field] = answer
                    opp.pending_question_field = None
                    step.note(f"{field} = {answer!r}")
                else:
                    # Empty text, or "Something else" was chosen: still
                    # waiting for the customer's actual free-text answer.
                    step.note(f"{field} still pending (no answer captured)")

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
        current_customer_message = opp.messages[-1]
        bound_evidence = []
        for evidence in det.posture_evidence:
            if evidence.span and evidence.span.casefold() in text.casefold():
                evidence.source_message_ids = [current_customer_message.id]
                bound_evidence.append(evidence)
        det.posture_evidence = bound_evidence
        if (
            det.buying_posture.value != "unknown" and bound_evidence
            and any(e.quality is EvidenceQuality.CLEAR for e in bound_evidence)
        ):
            opp.buying_posture = det.buying_posture
            opp.posture_evidence = list(bound_evidence)
            if det.buying_posture is BuyingPosture.DEFERRED:
                det.postponement = True
        elif det.buying_posture.value != "unknown":
            # An unsupported extraction is not allowed to overwrite current posture.
            det.buying_posture = type(det.buying_posture).UNKNOWN

        bound_transaction_evidence = []
        for evidence in det.transaction_evidence:
            if evidence.span and evidence.span.casefold() in text.casefold():
                evidence.source_message_ids = [current_customer_message.id]
                bound_transaction_evidence.append(evidence)
        det.transaction_evidence = bound_transaction_evidence
        if (
            det.transaction_issue is not TransactionIssue.NONE
            and bound_transaction_evidence
            and any(item.quality is EvidenceQuality.CLEAR for item in bound_transaction_evidence)
        ):
            # A customer-reported transaction outcome is not verified. Prevent
            # that same report from being treated as a purchase or conversion.
            det.signals = [
                signal for signal in det.signals
                if signal not in {Signal.CONVERSION, Signal.PURCHASE}
            ]
        elif det.transaction_issue is not TransactionIssue.NONE:
            det.transaction_issue = TransactionIssue.NONE

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
            evidence_ids = sorted({
                source_id for evidence in det.posture_evidence
                for source_id in evidence.source_message_ids
            })
            transaction_evidence_ids = sorted({
                source_id for evidence in det.transaction_evidence
                for source_id in evidence.source_message_ids
            })
            step.note(
                f"intent={det.intent.value} posture={det.buying_posture.value} "
                f"posture_evidence={','.join(evidence_ids) or '-'} "
                f"transaction_issue={det.transaction_issue.value} "
                f"transaction_evidence={','.join(transaction_evidence_ids) or '-'} "
                f"best={opp.best_intent.value} signals={len(opp.signals)}"
            )

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
                product_for_retrieval = opp.product
                # An advice-style question (eligibility, coverage, ...) where
                # no product has ever actually been named - by the customer,
                # this turn or earlier - should survey every plan's own field
                # rather than answer about whichever product extraction
                # inferred from unrelated wording ("my father is 90 years
                # old" -> Family). `product_rules.detect` is the same
                # literal-naming check retrieval already trusts elsewhere,
                # and it is context-aware, so a plan named earlier in the
                # conversation still correctly narrows the answer.
                if (
                    det.intent in PRODUCT_SURVEY_INTENTS
                    and product_rules.detect(text, context=context) is Product.UNKNOWN
                ):
                    product_for_retrieval = Product.UNKNOWN
                retrieval = self.retriever.retrieve(text, product_for_retrieval, det.intent)
            step.note(f"confidence={retrieval.confidence:.2f} facts={len(retrieval.facts)}")

        with recorder.step("hitl", "rule") as step:
            proposal = outcome.handoff
            # `evaluate` decides proposal acceptance internally (qualification,
            # takeover) and returns it encoded in `reason` itself — there is no
            # separate acceptance function to call. `proposal_accepted` here is
            # only for the diagnostic note below, derived from that same
            # returned reason rather than duplicating the acceptance check.
            policy_decision = (
                Decision(
                    action=DecisionAction.OFFER_HANDOFF,
                    reason_code="sales_followup",
                    reason=requested_handoff_reason,
                    evidence_message_ids=(pending_decision.evidence_message_ids
                                          if pending_decision else ()),
                )
                if requested_handoff_reason else hitl.decide(
                    opp, det, retrieval,
                    confidence_floor=config.RETRIEVAL_CONFIDENCE_ESCALATE,
                    customer_text=text,
                    proposal=proposal,
                    customer_message_id=current_customer_message.id,
                )
            )
            clarify_ready_without_referent = (
                det.buying_posture is BuyingPosture.READY_NOW
                and policy_decision.action is DecisionAction.CLARIFY
                and policy_decision.reason_code == "ready_without_referent"
            )
            reason = (
                policy_decision.reason
                if policy_decision.action in (
                    DecisionAction.OFFER_HANDOFF, DecisionAction.HOLD_FOR_STAFF
                ) else None
            )
            proposal_accepted = bool(reason) and reason.startswith(hitl.REASON_ASSISTANT_PROPOSED)
            case: Optional[HumanCase] = None
            case_updated = False
            if reason:
                # A human is taking this over, or about to be asked to
                # (handoff confirmation): a clarifying-question flow that was
                # mid-way through no longer applies.
                opp.pending_question_field = None
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
                    case_updated = True
                    opp.human_takeover = case.status is CaseStatus.TAKEN_OVER
                    opp.human_intervention_required = True
                else:
                    # No active case: request confirmation first
                    step.note(f"confirmation requested: {reason}")
                    opp.pending_handoff_reason = reason
                    opp.human_intervention_required = True
            detail = (
                f"action={policy_decision.action.value} "
                f"reason_code={policy_decision.reason_code}"
            )
            if reason:
                detail += f" reason={reason}"
            if policy_decision.evidence_message_ids:
                detail += f" evidence={','.join(policy_decision.evidence_message_ids)}"
            if proposal is not None and proposal.requested:
                detail += f"; proposal={proposal.reason!r} -> {'accepted' if proposal_accepted else 'declined'}"
            step.note(detail)

        with recorder.step("next_best_action", "rule") as step:
            queued_case = self.repo.active_case_for(opp.id)
            case_waiting_for_staff = bool(
                queued_case is not None and queued_case.status is CaseStatus.OPEN
            )
            nba = next_best_action.recommend(
                opp, det, escalated=bool(reason) or case_waiting_for_staff
            )
            step.note(nba.action)

        with recorder.step("clarifying_question", "rule") as step:
            if opp.pending_handoff_reason or nba.reply_mode in _NO_FACTS_REPLY_MODES:
                step.note("skipped: handoff pending or reply mode excludes selling")
            elif opp.product is Product.CORPORATE and "employee_count" not in opp.collected_answers:
                # Deterministic, not left to the model's own judgement: a
                # corporate customer who already states a headcount ("we have
                # 200 employees") has answered before being asked.
                mentioned = _EMPLOYEE_COUNT_MENTION.search(text)
                if mentioned:
                    opp.collected_answers["employee_count"] = mentioned.group(0).strip()
                    opp.pending_question_field = None
                    step.note(f"employee_count captured from message: {mentioned.group(0)!r}")
                elif not opp.pending_question_field:
                    opp.pending_question_field = "employee_count"
                    step.note("proposed employee_count (deterministic: corporate product)")
                else:
                    step.note("employee_count already pending")
            elif (
                outcome.question_field
                and outcome.question_field not in opp.collected_answers
                and not opp.pending_question_field
            ):
                opp.pending_question_field = outcome.question_field
                step.note(f"proposed {outcome.question_field} (model-proposed)")
            else:
                step.note("no question proposed")

        chips = quick_replies.suggest(opp, det)
        customer_facts: list[str] = []

        # 3. Composing segment: only a customer-safe projection crosses over.
        withdrawal = Signal.WITHDRAWAL in det.signals
        escalate = bool(reason)
        was_under_takeover = decision.active

        # Check if we need to request handoff confirmation
        if opp.pending_handoff_reason:
            reply_message = self._offer_handoff(opp, policy_decision, now)
            chips = self._handoff_chips()

            with recorder.step("response_generation", "template") as step:
                step.note(f"handoff_confirmation_requested reason={opp.pending_handoff_reason}")
        else:
            # Normal reply generation.
            # Build ReplyRequest from the kernel decision
            from ..agent.reply import ReplyRequest
            from ..knowledge import loader
            kb = loader.load()
            reply_budget = model_budget_for_turn(recorder, allow_tools=False)
            reply_request = ReplyRequest(
                action=nba,
                facts=list(retrieval.facts),
                customer_name=opp.customer_name,
                concern=opp.main_concern,
                customer_text=text,
                disclaimer=kb.disclaimer,
                history=opp.messages[:-1],  # All messages except the current customer message
                memory=outcome.memory,
                usage_limits=reply_budget.limits,
                model_allowed=reply_budget.allowed,
                model_budget_reason=reply_budget.reason,
                # `retrieval.product` is UNKNOWN only for the product-overview
                # case (`KnowledgeRetriever._product_overview`) - a short,
                # already-curated one-liner per plan, not a larger pool to pick
                # 1-2 fields from. Selecting *among* products there answers a
                # different question than "what plans are there".
                select_facts=retrieval.product is not Product.UNKNOWN,
            )

            # Some deterministic outcomes replace any composed answer below.
            # Decide those first so we do not spend a model call whose output
            # cannot reach the customer.
            fixed_reply = None
            if det.buying_posture is BuyingPosture.DEFERRED:
                fixed_reply = "Understood. I'll leave this here for now. You can come back whenever you're ready."
            if case_updated:
                if opp.human_takeover:
                    fixed_reply = "A representative is handling your request. I'll leave this conversation with them."
                else:
                    fixed_reply = "I've added this update to your existing request. A representative can review it when they take up your case."
            elif case_waiting_for_staff:
                fixed_reply = "Your request is in the staff queue. I can't make that decision here."
            if cancelled_readiness_invitation:
                fixed_reply = "Understood. I won't ask you to confirm that step again."
            if clarify_unanchored_affirmative:
                fixed_reply = (
                    "What would you like help with next? I can explain the application "
                    "steps or help with another question."
                )
            elif clarify_ready_without_referent:
                fixed_reply = "What would you like to do next? I can explain the application steps or answer another question."

            answer_gap = False
            if fixed_reply is not None:
                with recorder.step("response_generation", "template") as step:
                    step.note("deterministic response; model composition skipped")
                reply_text = fixed_reply
                reply_generation = Generation.TEMPLATE
            else:
                # 3. Composing segment: record both the model trace and the
                # final mode in the same run as extraction and the kernel.
                with recorder.step("response_generation", "template") as step:
                    reply_outcome = self.composer.compose(reply_request)
                    step.note(f"mode={nba.reply_mode.value} facts={len(reply_request.facts)}")
                    if reply_outcome.generation is Generation.LLM:
                        recorder.steps[-1].kind = "llm"
                        if reply_outcome.history:
                            telemetry.record_trace(
                                recorder,
                                reply_outcome.history,
                                purpose="response_generation",
                                finished_at=datetime.now().astimezone(),
                            )
                    if reply_outcome.degraded and not reply_outcome.by_design:
                        step.degrade(reply_outcome.degradation_reason or "degraded")
                reply_text = reply_outcome.text
                reply_generation = reply_outcome.generation
                customer_facts = list(reply_outcome.displayed_facts)
                # Retrieval confidence measures candidate quality, not whether
                # the final composer found an answer to this particular question.
                answer_gap = (
                    not customer_facts
                    and nba.reply_mode not in _NO_FACTS_REPLY_MODES
                )
            if answer_gap:
                policy_decision = Decision(
                    action=DecisionAction.OFFER_HANDOFF,
                    reason_code="knowledge_gap",
                    reason="No approved fact answered the customer's question",
                    evidence_message_ids=(current_customer_message.id,),
                )
                with recorder.step("answerability_guard", "rule") as step:
                    step.note(
                        "composer returned no displayed facts; "
                        "replaced unsupported answer with handoff confirmation"
                    )
                reply_message = self._offer_handoff(
                    opp, policy_decision, now, generation=reply_generation
                )
                chips = self._handoff_chips()
                nba = next_best_action.recommend(opp, det, escalated=True)
            else:
                if opp.pending_question_field:
                    reply_text = f"{reply_text}\n\n{questions.text_prompt(opp.pending_question_field)}"

                reply_message = Message(
                    role=MessageRole.BUSINESS,
                    text=reply_text,
                    author=MessageAuthor.AI,
                    generation=reply_generation,
                )
                if nba.reply_mode is ReplyMode.CLOSE and det.buying_posture not in {
                    BuyingPosture.DEFERRED, BuyingPosture.DECLINED,
                } and not clarify_ready_without_referent \
                        and not clarify_unanchored_affirmative \
                        and not cancelled_readiness_invitation:
                    opp.pending_action = PendingAction(
                        kind=ActionKind.READINESS_INVITATION,
                        reason_code="sales_followup",
                        reason="Customer was invited to signal readiness for next-step help",
                        originating_customer_message_id=next(
                            (message.id for message in reversed(opp.messages)
                             if message.role is MessageRole.CUSTOMER), None
                        ),
                        originating_assistant_message_id=reply_message.id,
                        status=ActionStatus.PENDING,
                        created_at=now,
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
    def _offer_handoff(
        opp: Opportunity,
        decision: Decision,
        now: datetime,
        *,
        generation: Generation = Generation.TEMPLATE,
    ) -> Message:
        """Ask for consent and persist a pending handoff without creating a case."""
        reason_explanations = {
            "payment_reported": "you reported a payment and I can't verify whether it was received",
            "payment_failed": "your payment attempt needs staff review",
            "payment_unconfirmed": "the charge has no confirmation and I can't verify the policy status",
            "order_status": "I can't access or verify the order or application status",
            "human_request": "you asked to speak with a person",
            "complaint": "your complaint needs a representative's review",
            "restricted_decision": "this request requires a staff decision",
            "custom_quote": "a representative needs to review or prepare this quote",
            "knowledge_gap": "I don't have approved information that answers your question",
            "sales_followup": "you asked for help with the next step",
            "assistant_proposal": "this request needs a representative's review",
            "staff_review": "this request needs a representative's review",
        }
        explanation = reason_explanations.get(
            decision.reason_code, "this request needs a representative's review"
        )
        reply_message = Message(
            role=MessageRole.BUSINESS,
            text=(
                f"Because {explanation}, I can submit this conversation to a "
                "representative for review. Would you like me to? Reply 'Confirm' or 'Cancel'."
            ),
            author=MessageAuthor.AI,
            generation=generation,
        )
        opp.pending_handoff_reason = decision.reason
        opp.human_intervention_required = True
        opp.pending_question_field = None
        opp.pending_action = PendingAction(
            kind=ActionKind.HANDOFF,
            reason_code=decision.reason_code,
            reason=decision.reason or "Customer requested a representative",
            originating_customer_message_id=next(
                (message.id for message in reversed(opp.messages)
                 if message.role is MessageRole.CUSTOMER), None
            ),
            originating_assistant_message_id=reply_message.id,
            status=ActionStatus.PENDING,
            created_at=now,
        )
        opp.messages.append(reply_message)
        return reply_message

    @staticmethod
    def _handoff_answer(text: str) -> Optional[bool]:
        """Parse customer's handoff confirmation response.

        Returns True for confirmation, False for cancellation, None for other responses.
        """
        normalized = " ".join(text.lower().split()).strip(".!? ")
        if normalized in {
            "confirm", "yes", "yes please", "please do", "yes im ready",
            "yes i'm ready", "yes i’m ready", "i'm ready", "i’m ready",
            "i am ready", "ready", "go ahead", "确认", "是", "好的",
        }:
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
        if opp.pending_action is not None:
            opp.pending_action.status = (
                ActionStatus.CONFIRMED if confirmed else ActionStatus.CANCELLED
            )
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

            # Customer confirmation creates a queued case; staff ownership starts
            # only when the representative explicitly moves it to TAKEN_OVER.
            opp.human_takeover = False
            opp.human_intervention_required = True
            reply_text = (
                "I've added your request to the staff queue. "
                "A representative can contact you after reviewing it."
            )
        else:
            # Customer cancelled: continue with AI
            opp.human_intervention_required = False
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
    if det.transaction_issue is TransactionIssue.NONE:
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
