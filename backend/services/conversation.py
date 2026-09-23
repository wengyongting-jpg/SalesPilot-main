# -*- coding: utf-8 -*-
"""One customer message, end to end. The orchestrator.

This is where the central claim of `docs/backend-plan.md` §3 is either true or not:

    the model leads the observing segment, choosing read-only tools
    THE KERNEL RUNS HERE - unconditionally, exactly once, in a fixed order
    the model leads the composing segment, continuing the same conversation

The kernel is a sequence of plain calls in `_run_kernel` below. That is the whole
argument for not making it a tool: "exactly once, in this order" is a property of
these lines rather than of a framework's configuration, it holds identically when no
model is configured at all, and it still holds when a provider times out halfway
through the run.

The order is not arbitrary. Transition first, because the score is computed against
the new state. Score before the action, because the action reads the band. Retrieval
before escalation, because the escalation rules read retrieval confidence. Getting
these wrong produces plausible wrong numbers rather than an error, which is why the
test suite asserts the ordering rather than trusting the reading.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional

from .. import config
from ..agent.runtime import AgentRuntime
from ..domain.case import HumanCase
from ..domain.decision import NextBestAction
from ..domain.detection import Detection, RetrievalResult
from ..domain.enums import Generation, Qualification, ReplyMode
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
    profile,
    qualification,
    quick_replies,
    scoring,
    state_machine,
    takeover,
)
from ..kernel.quick_replies import QuickReply
from ..agent.reply import ReplyOutcome
from ..knowledge import questions as question_tools
from ..knowledge import loader
from ..knowledge.keyword import KeywordRetriever
from ..observability.logging import get_logger, log_run
from ..observability.recorder import RunRecorder
from ..observability.run import StepKind
from ..knowledge.availability import customer_note
import uuid
import re


class QuestionAnswerTooLong(ValueError):
    """A free-form answer exceeded the approved customer question limit."""


@dataclass
class ConversationResult:
    """Everything one message produced, for both visibility tiers to project from.

    `to_dict()` is the single serialisation. A replay returns the stored payload from
    the same method, so the API has one code path and a replayed response cannot drift
    from a live one.
    """

    reply: str = ""
    message: Optional[Message] = None
    opportunity: Optional[Opportunity] = None
    detection: Optional[Detection] = None
    retrieval: Optional[RetrievalResult] = None
    score: Optional[ScoreCard] = None
    state_change: str = ""
    next_best_action: Optional[NextBestAction] = None
    case: Optional[HumanCase] = None
    quick_replies: list = field(default_factory=list)
    customer_facts: list = field(default_factory=list)
    extraction_source: str = "rules"
    client_message_id: Optional[str] = None
    replayed: bool = False
    agent_run: Optional[Any] = None
    _payload: Optional[dict] = None

    @classmethod
    def replay(cls, payload: dict) -> "ConversationResult":
        return cls(
            reply=payload.get("reply", ""),
            quick_replies=payload.get("quick_replies", []),
            extraction_source=payload.get("extraction_source", "rules"),
            client_message_id=payload.get("client_message_id"),
            replayed=True,
            _payload=payload,
        )

    def to_dict(self) -> dict:
        if self._payload is not None:
            return self._payload
        from .serialisation import result_to_dict

        return result_to_dict(self)


class ConversationService:
    def __init__(
        self,
        repo,
        *,
        model=None,
        kb=None,
        runtime: Optional[AgentRuntime] = None,
        retriever: Optional[KeywordRetriever] = None,
        now: Callable[[], datetime] = datetime.now,
        capture_content: Optional[bool] = None,
        trace: Optional[bool] = None,
    ) -> None:
        self.repo = repo
        self.kb = kb or loader.load()
        self.runtime = runtime or AgentRuntime(kb=self.kb, model=model)
        self.retriever = retriever or KeywordRetriever(self.kb)
        self.now = now
        self.capture_content = (
            config.TELEMETRY_CONTENT if capture_content is None else capture_content
        )
        self.trace = trace
        self.logger = get_logger()

    # ---- Entry point -----------------------------------------------------

    def handle_customer_message(
        self,
        *,
        customer_id: str,
        customer_name: str,
        text: str,
        client_message_id: Optional[str] = None,
    ) -> ConversationResult:
        key = (client_message_id or "").strip() or None
        scope = (customer_id or "").strip()

        # Idempotency first, before anything mutates. A blank customer_id means a
        # fresh conversation, so no earlier receipt can exist for it.
        if key and scope:
            stored = self.repo.get_message_receipt(scope, key)
            if stored is not None:
                self.logger.info("replay | %s | key=%s", scope, key)
                return ConversationResult.replay(stored)

        opp = self._load_or_create(scope, customer_name)
        if opp.pending_question_field and len(text.strip()) > 200:
            raise QuestionAnswerTooLong("Please keep this answer under 200 characters")
        recorder = RunRecorder(
            opportunity_id=opp.id,
            client_message_id=key,
            customer_message_count=opp.customer_message_count + 1,
            capture_content=self.capture_content,
            content_max_chars=config.TELEMETRY_CONTENT_MAX_CHARS,
            now=self.now,
        )

        opp.customer_message_count += 1
        customer_message = Message.from_customer(text, client_message_id=key)
        opp.messages.append(customer_message)

        if opp.pending_handoff_reason:
            answer = self._handoff_answer(text)
            if answer is not None:
                return self._resolve_handoff(
                    opp, answer, key=key, recorder=recorder,
                )
            # A different customer request supersedes the offer. Evaluate it afresh;
            # never treat a non-answer as implicit permission to contact a person.
            opp.pending_handoff_reason = None
        if opp.pending_question_field:
            answer = question_tools.normalise_answer(opp.pending_question_field, text)
            if answer is None:
                return self._question_other_reply(opp, key=key, recorder=recorder)
            opp.collected_answers[opp.pending_question_field] = answer
            opp.pending_question_field = None
            text = answer

        observation = self._observe(opp, text, recorder)
        verdict = self._run_kernel(
            opp,
            observation.extraction.detection,
            text,
            recorder,
            extraction_source=observation.extraction.source,
            question_field=observation.tool_context.question_field,
        )
        reply = self._compose(opp, observation, verdict, recorder)

        business_message = Message.from_ai(reply.text, generation=reply.generation)
        opp.messages.append(business_message)

        run = recorder.finish()
        self.repo.upsert_opportunity(opp)
        self.repo.save_agent_run(run)
        log_run(run, trace=self.trace)

        result = ConversationResult(
            reply=reply.text,
            message=business_message,
            opportunity=opp,
            detection=observation.extraction.detection,
            retrieval=verdict.retrieval,
            score=verdict.score,
            state_change=verdict.state_change,
            next_best_action=verdict.action,
            case=verdict.case,
            quick_replies=(
                self._handoff_chips() if opp.pending_handoff_reason
                else verdict.quick_replies
            ),
            customer_facts=verdict.customer_facts,
            extraction_source=observation.extraction.source,
            client_message_id=key,
            agent_run=run,
        )

        if key:
            # Keyed on the resolved id, so a generated one is deduplicated on any
            # later replay too.
            self.repo.save_message_receipt(opp.id, key, result.to_dict())
        return result

    # ---- Segment 1 -------------------------------------------------------

    def _observe(self, opp: Opportunity, text: str, recorder: RunRecorder):
        with recorder.step("extraction", StepKind.LLM) as step:
            observation = self.runtime.observe(text, opportunity=opp)
            extraction = observation.extraction
            if extraction.degraded:
                step.degraded(
                    extraction.degradation_reason or "degraded",
                    by_design=extraction.by_design,
                )
            for violation in extraction.violations:
                step.violation(violation)
            for note in extraction.rule_notes:
                step.note(note)
            recorder.record_tool_calls(observation.tool_context.calls)
            self._record_usage(recorder, observation.usage)
        return observation

    # ---- The kernel: mandatory, exactly once, fixed order ----------------

    def _run_kernel(
        self,
        opp: Opportunity,
        det: Detection,
        text: str,
        recorder: RunRecorder,
        *,
        extraction_source: str,
        question_field: Optional[str] = None,
    ) -> "KernelVerdict":
        previous_state = opp.state
        previous_score = opp.score

        with recorder.step("takeover", StepKind.RULE) as step:
            decision = takeover.evaluate(opp, det)
            step.note(decision.reason)

        with recorder.step("state_transition", StepKind.RULE) as step:
            transition = state_machine.transition(opp.state, det)
            if decision.freeze_state:
                step.note("state frozen under human takeover")
            else:
                opp.state = transition.new_state
            step.note(f"{previous_state.value} -> {opp.state.value}")

        with recorder.step("profile_update", StepKind.RULE):
            profile.apply_observations(
                opp, det, text,
                transition=None if decision.freeze_state else transition,
            )
            message_id = opp.messages[-1].id
            opp.evidence_sources["latest"] = message_id
            if det.intent is opp.best_intent:
                opp.evidence_sources["intent"] = message_id
            if det.product is opp.product:
                opp.evidence_sources["product"] = message_id
            for signal in det.signals:
                opp.evidence_sources[f"signal:{signal.value}"] = message_id
            if scoring.urgency_in(text):
                opp.evidence_sources["urgency"] = message_id

        with recorder.step("qualification", StepKind.RULE) as step:
            gate = qualification.assess(opp, det)
            opp.qualification = gate.level
            opp.qualification_reason = gate.reason
            if gate.level is not Qualification.QUALIFIED:
                step.note(f"{gate.level.value}: {gate.reason}")

        with recorder.step("scoring", StepKind.RULE) as step:
            score = scoring.score(opp, det, text, now=self.now())
            if (
                decision.preserve_score_floor
                and previous_score is not None
                and score.total < previous_score.total
            ):
                step.note("score floor preserved under human takeover")
                score = previous_score
            opp.score = score
            step.note(
                f"fit {score.fit_total} / behaviour {score.behaviour_total} "
                f"-> {score.priority.value}"
            )

        with recorder.step("next_best_action", StepKind.RULE):
            action = next_best_action.recommend(opp, det, escalated=False)

        # Before escalation, because the escalation rules read its confidence.
        with recorder.step("knowledge_retrieval", StepKind.RETRIEVAL) as step:
            retrieval = self.retriever.retrieve(text, opp.product, det.intent)
            step.note(f"{len(retrieval.facts)} facts, confidence {retrieval.confidence}")

        with recorder.step("hitl", StepKind.RULE) as step:
            case = self._escalate_if_needed(opp, det, retrieval, action, step, text)
            if case is not None:
                action = next_best_action.recommend(opp, det, escalated=True)

        if (
            not opp.pending_handoff_reason and not opp.human_takeover
            and case is None and question_field in question_tools.CATALOG
            and question_field not in opp.collected_answers
            and det.intent.value in {"generic", "family_need", "corporate_need"}
        ):
            opp.pending_question_field = question_field

        # P0-3: takeover forces human handling even when this message did not
        # independently re-trigger escalation.
        if opp.human_takeover and not action.human_intervention_required:
            action = NextBestAction(
                action="Human take-over active: a representative is handling the customer",
                reason="Human takeover is active, so the assistant does not resume selling",
                priority=action.priority,
                reply_mode=ReplyMode.HANDOVER,
                human_intervention_required=True,
            )

        with recorder.step("quick_replies", StepKind.RULE):
            chips = (
                self._handoff_chips() if opp.pending_handoff_reason
                else [] if opp.pending_question_field
                else quick_replies.suggest(opp, det)
            )
            if (
                not opp.pending_handoff_reason and not opp.pending_question_field
                and len(retrieval.facts) > 2
                and action.reply_mode not in (
                    ReplyMode.HOLD, ReplyMode.WITHDRAWN, ReplyMode.HANDOVER,
                )
            ):
                chips = [quick_replies.more_details(), *chips][:3]

        opp.score_history.append(
            ScoreHistoryEntry(
                timestamp=self.now(),
                score=opp.score.total,
                state=opp.state.value,
                # Step kind describes the logical pipeline slot and remains "llm"
                # even when its rule-based peer handled the work. Record the actual
                # extraction source so offline runs are never presented as model use.
                trigger=f"message({extraction_source})",
                evidence=scoring.explain(opp, det, opp.score),
            )
        )
        if previous_state is not opp.state:
            opp.state_history.append(
                StateHistoryEntry(
                    timestamp=self.now(),
                    from_state=previous_state.value,
                    to_state=opp.state.value,
                    reason=transition.reason,
                )
            )

        return KernelVerdict(
            score=opp.score,
            action=action,
            case=case,
            retrieval=retrieval,
            quick_replies=chips,
            state_change=(
                f"{previous_state.value} -> {opp.state.value} ({transition.reason})"
            ),
            customer_facts=(
                [] if opp.pending_handoff_reason or opp.pending_question_field
                else self._facts_for(action, retrieval, text)
            ),
        )

    def _escalate_if_needed(self, opp, det, retrieval, action, step, text):
        reason = hitl.evaluate(opp, det, retrieval, customer_text=text)
        if reason is None:
            return None

        existing = self.repo.active_case_for(opp.id)
        if existing is not None:
            # One active case per opportunity: update rather than open a second, so a
            # queue never shows the same customer twice.
            existing.reason = reason
            existing.state = opp.state
            existing.recommended_action = action.action
            existing.summary = f"{existing.summary} [Update] {hitl.summarise(opp)}"
            self.repo.update_case(existing)
            return existing
        step.note(f"confirmation requested: {reason}")
        opp.pending_handoff_reason = reason
        opp.human_intervention_required = True
        return None

    # ---- Segment 2 -------------------------------------------------------

    def _compose(self, opp, observation, verdict, recorder: RunRecorder):
        if opp.pending_handoff_reason:
            reason = opp.pending_handoff_reason
            if reason == hitl.REASON_HUMAN_REQUEST:
                prefix = "Would you like me to notify a CareSure representative?"
            elif reason == hitl.REASON_COMPETITIVE:
                prefix = "A representative can help with the next step. Shall I notify the team?"
            else:
                prefix = (
                    "That needs a representative's review; I cannot decide it here. "
                    "Shall I notify the team?"
                )
            return ReplyOutcome(
                text=(
                    f"{prefix} {customer_note(self.now())} "
                    "Reply 'Confirm' or 'Cancel'."
                ),
                generation=Generation.TEMPLATE,
            )
        if opp.pending_question_field:
            return ReplyOutcome(
                text=question_tools.text_prompt(opp.pending_question_field),
                generation=Generation.TEMPLATE,
            )
        with recorder.step("response_generation", StepKind.LLM) as step:
            reply = self.runtime.compose(
                observation,
                action=verdict.action,
                facts=verdict.customer_facts,
                customer_name=opp.customer_name,
                concern=opp.main_concern,
                disclaimer=self.kb.disclaimer,
            )
            if reply.degraded:
                step.degraded(
                    reply.degradation_reason or "degraded",
                    by_design=reply.by_design,
                )
            if reply.disclaimer_appended:
                step.note("approved premium disclaimer appended by deterministic guard")
            for violation in reply.violations:
                step.violation(violation)
            self._record_usage(recorder, reply.usage)
        return reply

    @staticmethod
    def _handoff_chips() -> list[QuickReply]:
        return [
            QuickReply("handoff_confirm", "Confirm"),
            QuickReply("handoff_cancel", "Cancel"),
        ]

    @staticmethod
    def _handoff_answer(text: str) -> Optional[bool]:
        normal = " ".join(text.lower().split()).strip(".!? ")
        if normal in {"confirm", "yes", "yes please", "please do", "确认", "是", "好的"}:
            return True
        if normal in {"cancel", "no", "no thanks", "not now", "取消", "否", "不用"}:
            return False
        return None

    def _resolve_handoff(
        self, opp: Opportunity, confirmed: bool, *, key: Optional[str],
        recorder: RunRecorder,
    ) -> ConversationResult:
        reason = opp.pending_handoff_reason or "Customer requested a representative"
        opp.pending_handoff_reason = None
        case = None
        if confirmed:
            case = self.repo.active_case_for(opp.id)
            if case is None:
                case = HumanCase(
                    opportunity_id=opp.id,
                    customer_name=opp.customer_name,
                    state=opp.state,
                    product=opp.product,
                    reason=reason,
                    summary=hitl.summarise(opp),
                    recommended_action="A representative should review the conversation",
                )
                self.repo.add_case(case)
            opp.human_takeover = True
            opp.human_intervention_required = True
            text = (
                "Confirmed. I've sent your conversation to the CareSure team. "
                "A representative will follow up when available."
            )
        else:
            opp.human_intervention_required = False
            text = (
                "Understood. I won't notify a representative now. "
                "I can still help with general plan information."
            )
        message = Message.from_ai(text, generation=Generation.TEMPLATE)
        opp.messages.append(message)
        run = recorder.finish()
        self.repo.upsert_opportunity(opp)
        self.repo.save_agent_run(run)
        log_run(run, trace=self.trace)
        result = ConversationResult(
            reply=text, message=message, opportunity=opp, case=case,
            client_message_id=key, agent_run=run,
        )
        if key:
            self.repo.save_message_receipt(opp.id, key, result.to_dict())
        return result

    def _question_other_reply(
        self, opp: Opportunity, *, key: Optional[str], recorder: RunRecorder,
    ) -> ConversationResult:
        text = "Please describe your answer in your own words."
        message = Message.from_ai(text, generation=Generation.TEMPLATE)
        opp.messages.append(message)
        run = recorder.finish()
        self.repo.upsert_opportunity(opp)
        self.repo.save_agent_run(run)
        log_run(run, trace=self.trace)
        result = ConversationResult(
            reply=text, message=message, opportunity=opp,
            client_message_id=key, agent_run=run,
        )
        if key:
            self.repo.save_message_receipt(opp.id, key, result.to_dict())
        return result

    # ---- Cost accounting -------------------------------------------------

    @staticmethod
    def _record_usage(recorder: RunRecorder, usage) -> None:
        """File what a model call consumed, if there was one.

        `None` means no model ran - the offline peers - and recording nothing is then
        the honest answer. What must never happen is a model call going unrecorded: the
        run would report `llm_call_count: 0` and `cost.pricing_known: true` with an
        amount of zero, which reads as "this was free" rather than "this was never
        measured". That was live for the whole of P4 to P6, because the recorder was
        tested without this caller and the only service-level assertion about the count
        ran on the offline path, where zero is correct.
        """
        if usage is None:
            return
        recorder.record_llm_call(
            purpose=usage.purpose,
            model=usage.model,
            duration_ms=usage.duration_ms,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            input_text=usage.input_text,
            output_text=usage.output_text,
        )

    # ---- Reset -----------------------------------------------------------

    def generate_staff_brief(self, opportunity_id: str) -> Optional[dict]:
        """On-demand staff-only brief, grounded in the stored conversation."""
        opp = self.repo.get_opportunity(opportunity_id, history_limit=0)
        case = self.repo.active_case_for(opportunity_id)
        if opp is None or case is None:
            return None
        latest_customer = next(
            (message for message in reversed(opp.messages)
             if message.role.value == "customer"), None,
        )
        evidence = {
            "need": opp.main_concern or "not yet established",
            "product": opp.product.value,
            "handoff_reason": case.reason,
            "priority": opp.priority.value if opp.priority else "unknown",
            "score": opp.final_score,
            "keywords": [signal.value for signal in opp.signals[:5]],
            "latest_message": latest_customer.text[:500] if latest_customer else "none",
            "latest_message_id": latest_customer.id if latest_customer else None,
        }
        draft = self.runtime.draft_staff_brief(evidence)
        usage = draft["usage"]
        return {
            "text": draft["text"],
            "source": draft["source"],
            "evidence": evidence,
            "usage": {
                "model": usage.model,
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
                "duration_ms": usage.duration_ms,
            } if usage else None,
        }

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
        if existed:
            self.logger.info("reset | %s", conversation_id)
        return existed

    @staticmethod
    def _facts_for(
        action: NextBestAction, retrieval: RetrievalResult, text: str = ""
    ) -> list[str]:
        """Which approved facts may be used at all this turn.

        One list, used both to prompt the composer and as the customer-visible
        `facts`. That is deliberate: the customer app renders these as product cards,
        and returning a premium alongside a "a representative will be in touch" reply
        would put a price card under a handover message. The reply and the cards have
        to agree, so there is one decision rather than two.

        Empty when the conversation is not being sold to. Handing a composer a premium
        figure invites it into the text regardless of what the guidance says.
        """
        if action.reply_mode in (
            ReplyMode.HOLD, ReplyMode.WITHDRAWN, ReplyMode.HANDOVER,
        ):
            return []
        facts = list(retrieval.facts)
        detailed = bool(re.search(
            r"\b(detail|details|specifically|full|explain|tell me more)\b",
            text, re.IGNORECASE,
        ))
        return facts if detailed else facts[:2]

    # ---- Internals -------------------------------------------------------

    def _load_or_create(self, customer_id: str, customer_name: str) -> Opportunity:
        if customer_id:
            existing = self.repo.get_opportunity(customer_id)
            if existing is not None:
                return existing
        return Opportunity(
            id=customer_id or f"C-{uuid.uuid4().hex[:6].upper()}",
            customer_name=customer_name,
        )


@dataclass
class KernelVerdict:
    """The deterministic layer's output for one message."""

    score: ScoreCard
    action: NextBestAction
    case: Optional[HumanCase]
    retrieval: RetrievalResult
    quick_replies: list
    state_change: str
    # The facts the assistant may use this turn, which is also exactly what the
    # customer tier returns. `retrieval.facts` is what was found; this is what is
    # allowed to be said.
    customer_facts: list = field(default_factory=list)
