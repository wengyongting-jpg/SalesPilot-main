# Backend decision-chain repair plan

**Status:** Original implementation handoff plan prepared 2026-09-26. The typed observation, pending-action, decision and execution chain is now implemented and offline-verified; the plan below records its original proposed sequence. The conversation ruleset's candidate numerical score weights remain unapproved and are not production policy. See [semantic and logic verification](semantic-and-logic-verification.md) for current findings and limits.

## Purpose and scope

Repair the backend chain from **observation → deterministic decision → persisted action → customer-facing response**. The immediate failure was a high-intent customer answering “yes im ready” after an assistant invitation: extraction identified `application`, but no handoff request or case followed, and the reply composer repeated a product-answer template. A narrow text rule now catches that exact pattern; it is a temporary safeguard, not the intended architecture.

This plan covers the backend's interpretation, current buying posture, risk boundaries, handoff confirmation, staff-case execution, and traceability. It does **not** authorize automatic ordering, binding quotes, a new staff-priority score, wholesale adoption of the candidate score table, a public v1 API change, or unconstrained model-written replies. Natural-language reply generation is a follow-on change once the decision/action contract is reliable; its integration seam is specified below.

Read [the proposed ruleset](conversation-ruleset-proposal.md), [its Chinese translation](conversation-ruleset-proposal.zh-CN.md), [the implemented memory repair](conversation-memory-repair-plan.md), `AGENTS.md`, and `backend/README.md` before editing. Preserve the frozen `docs/v0.0/api/interface-v1.md` contract. Do not overwrite unrelated working-tree changes; in particular, inspect `evals/v1-ruleset-validation.json` before touching evaluation material.

## Current path and observed mismatch

`ConversationService.handle_customer_message` appends the customer message to the in-flight opportunity, invokes model/rule extraction, then runs takeover, qualification, state transition, profile update, scoring, retrieval, HITL, next-best-action, clarification, reply composition, and storage. `Detection` reports `intent`, `product`, signals and flags, but has no explicit **current buying posture with evidence** or typed response to a pending action. `Opportunity.best_intent` retains historical strength; it cannot itself answer whether the customer is still ready now.

`hitl.evaluate` considers restricted topics, explicit human requests, weak factual retrieval, competitive pressure and a model handoff proposal. The recent `_READY_TO_PROCEED` phrase check additionally looks at the previous assistant *text*. It is fragile: paraphrases and languages are missed, and wording is being used as workflow state. `next_best_action.recommend` may set `human_intervention_required=True` for a high-intent sales recommendation, while `ConversationService` only persists its own intervention flag when HITL returns a reason. Thus a recommendation, a pending confirmation, an open case and actual staff takeover can diverge.

The current reply model selects indices of approved facts; a template writes the final prose. It receives the latest customer message and retrieved facts but does not author a conversational response. Product facts are not a substitute for a workflow answer such as “I am ready.” The product JSON contains plan fields, FAQ and a demo premium disclaimer; staff availability, question choices, conversation memory and workflow state live elsewhere.

## Target contract

Keep four distinct records, each with an explicit source and status:

1. **Observation:** the customer's current task intent, current buying posture (`unknown`, `browsing`, `evaluating`, `conditional`, `ready_now`, `deferred`, `declined`), objections, risk boundaries, and any proposed action response. Each non-default claim carries source message ID(s), a short supporting span and evidence quality. Model output is an observation, not an order or case mutation.
2. **Decision:** a deterministic, versioned policy chooses an allowed response action: `answer`, `clarify`, `offer_handoff`, `acknowledge_cancellation`, `confirm_handoff`, `hold_for_staff`, or equivalent typed internal values. It records why, what source evidence was accepted, and which restrictions remain. Task intent and buying posture are independent: `application` can be a process question without `ready_now`.
3. **Execution:** the service applies the decision once, atomically with its durable turn/receipt where supported. An offer is not a case; confirmation creates or updates one active case; cancellation clears the offer but not answer restrictions; an existing staff-owned case prevents autonomous AI selling. Repeated delivery of the same client message ID cannot create a second case.
4. **Response:** compose only from the executed outcome and allowed, sourced facts. Never say “submitted,” “assigned,” or “staff will contact you shortly” before the corresponding durable action or verified service-time data exists. The customer projection must not leak internal labels, score or priority.

Persist the pending customer action as a typed record (proposed fields: kind, reason code, originating assistant/customer message IDs, status and timestamp), rather than recovering it from assistant prose. Plan a migration from `pending_handoff_reason` and keep its v1 projection/compatibility behavior until an approved contract version supersedes it. A bare “yes” is confirmation only when exactly one relevant, still-pending prompt exists; otherwise clarify. A customer can state readiness without being automatically signed up or assigned to staff: issue the approved Confirm/Cancel offer first. A direct human request also receives that offer immediately. Define reason codes separately from customer-facing explanations.

## Implementation sequence

### Round 0 — Baseline and decision inventory

- Record the current Git diff and do not discard existing edits. Capture the offline suite and 24-conversation baseline; classify expected failures rather than changing old expectations silently.
- Trace at least the reported ready-to-proceed conversation and one each of price-only, deferral-after-readiness, direct human request, restricted medical/claim decision, complaint, handoff cancellation and repeat delivery. Separate extraction, kernel, execution and response failures in the run record.
- Obtain product-owner adjudication for disputed gold labels and the exact meaning of “ready now” versus “ask how to apply.” Keep customer buying posture separate from staff work urgency. Do not treat the candidate score numbers as calibrated facts.

### Round 1 — Typed observation and contextual evidence

- Extend the internal extraction schema and `Detection`-adjacent types to represent current posture, risk boundary, evidence spans/message IDs and uncertainty. Reuse the already bounded recent history, sourced memory and history-search tool. Verify evidence IDs refer to original messages; a summary note alone is not proof.
- Teach model and offline peer the same semantic contract. Negation, conditions, time and latest-message corrections must be resolved before historical signals are reused. Keep narrow deterministic overrides only for high-confidence safety triggers, and log disagreements rather than silently merging contradictory posture values.
- Preserve the public v1 `Intent`/`Signal`/`State` values until a separately approved API delta. If new internal fields are persisted, migrate SQLite explicitly and test a pre-migration database copy. Do not copy sensitive medical detail into opportunity summaries or derived evidence.

### Round 2 — Pure decision policy

- Refactor `kernel/hitl.py`, `state_machine.py`, `next_best_action.py` and any scoring inputs around the typed observation and typed pending action. The policy returns a **decision object**, not a phrase that the service must interpret. State precedence explicitly: existing staff ownership; restricted-answer boundary; pending confirmation response; direct human request; other staff need; ordinary factual answer/clarification.
- `ready_now` is not itself a verified sale. When it follows an assistant offer of staff help, propose confirmation; when it appears without a clear referent, ask what next step the customer wants. Do not gate this on the opportunity's historical High Intent badge or on a literal assistant sentence. A later `deferred` or `declined` supersedes present readiness, without erasing historical evidence.
- Keep current scoring behavior as a baseline in this round. Evaluate the proposed posture-based `two_axis_v2` separately using adjudicated offline labels and pairwise invariants before switching a score or public priority field. A complaint or restricted task may need staff even when sales posture is low.

### Round 3 — Transactional execution and response contract

- Make `services/conversation.py` execute the typed decision and persist proposal, customer confirmation/cancellation, case creation/update and staff takeover as separate auditable events. Reuse one active case per opportunity and the existing idempotency receipt. Ensure saved state and returned reply agree; failure to save a case must not produce a success message.
- Keep approved Confirm/Cancel chips and text fallback. After cancellation, clear only the pending request; do not answer the original restricted question. After staff takeover, the AI does not resume autonomous conversation or overwrite staff work.
- Pass the composer a customer-safe **executed-action envelope** (allowed response type, facts with source IDs, what actually happened, and any known availability), not internal score or a sales instruction. Initially the template can consume it; a later model-written composer must obey the same envelope and be checked for unsupported product claims, missing premium disclaimer, invented times/forms/links and claims of unexecuted actions. A model failure falls back safely and is visible in telemetry.
- Reconcile `human_intervention_required`, next-best-action recommendation, pending offer and actual `human_takeover` so each has one documented meaning. Do not silently equate sales-priority `HIGH` with staff queue urgency.

### Round 4 — Verification and rollout gate

- With owner approval for new test code, add pure offline policy tests and service-level multi-turn tests. At minimum assert: ready reply after an actual offer → one pending confirmation; Confirm or clear contextual affirmative → exactly one case; Cancel → no case and restrictions retained; duplicate client ID → unchanged outcome; unrelated “yes” → no case; price-only → no ready posture; deferral after ready → current posture drops; complaint with no purchase → staff path; claimed payment → no official lifecycle change; restricted question → no substantive AI answer.
- Run existing backend tests in offline mode, the multi-turn baseline, migration/reopen checks and frontend contract checks if the wire changes. Then run a bounded, explicitly authorized live-model sample with request/tool/iteration/cost ceilings; compare extraction correctness, action correctness, unsupported claims and customer-facing consistency separately. Do not declare success from aggregate accuracy alone: missed required handoffs and false claims are high-severity failures.
- Ship behind a reversible ruleset version/feature flag if score or state semantics change. Record old/new decisions side by side before cutover. Update current documentation and UI wording only after owner approval and after the final behavior is known; never edit the frozen v1 contract in place.

## Handoff for the implementing agent

Start with `backend/domain/detection.py`, `backend/domain/opportunity.py`, `backend/agent/extraction/model_based.py`, `backend/agent/extraction/rules/`, `backend/kernel/`, `backend/services/conversation.py`, `backend/storage/`, and `backend/evals/`. The highest-value first deliverable is a persisted, typed pending action plus a pure decision path that makes the reported “yes im ready” conversation produce the right Confirm/Cancel state **without reading prior assistant wording**. Do not begin by adding more English regex variants or by changing the reply prompt.

Report each round's changed files, before/after trace for the same multi-turn conversation, regression results and unresolved decisions. Ask the owner before adding test cases, changing a public contract, adopting candidate score weights, or adding model-authored customer prose. No paid live evaluation or remote Git mutation is implied by this document.
