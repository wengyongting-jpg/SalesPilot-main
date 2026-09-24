# SalesPilot persistence and evaluation repair plan

Status: **implemented; local acceptance gates passed 2026-09-25**

Baseline: `salespilot-v1.0`, created from `merge_test` at `b6fe80e`

Scope: backend persistence and evaluation. No frontend or public API change is proposed.

## Decision to review

Use the existing file-backed SQLite repository as the durable source of truth for
conversations, opportunity state, handoff state, cases, idempotency receipts, and
agent-run records. For this prototype, keep the complete opportunity in the existing
`opportunities.payload` JSON and use selected table columns only for filtering and
aggregation. Objects held by the running process are temporary working copies, not
a second source of truth.

Keep the approved product facts in `backend/knowledge/data/knowledge_base.json`,
loaded into a process-local cache. Keep prompts and business rules in versioned code.
Do not add a vector database, a separate prompt store, or few-shot examples merely
because those facilities exist. Evaluation cases are tests, not examples sent to the
model. Add a small, reviewed few-shot set only if a repeatable model failure remains
after persistence and knowledge problems are corrected.

The `messages`, `score_history`, and `state_history` tables are declared in
`schema.sql`. Keep the opportunity JSON payload as the source of truth for these
records; use the message index only for scoped history search. Leave the other
history tables in place. Do not migrate or delete user data as part of this repair.
Reconsider normalization only if actual conversation size or incremental-query
performance requires it.

## Historical verified baseline (before repair)

- The file-backed service uses `SqliteRepository`; the current 20-case backend eval
  and most HTTP tests use `InMemoryRepository`.
- The 20-case offline suite passes 20/20 with memory storage but only 13/20 when
  the same runner is supplied an in-memory SQLite repository. Seven handoff cases
  fail at the confirmation turn.
- The domain object contains `pending_handoff_reason`, `pending_question_field`,
  `collected_answers`, and `evidence_sources`; `storage/codec.py` currently omits
  them. Score-history evidence is also omitted.
- A live HTTP smoke test reproduced the defect: the first request offered
  Confirm/Cancel, but `Confirm` did not create a case because the pending state
  had vanished on the SQLite round trip.
- The `agent_runs` table declares queryable token and cost columns, but
  `SqliteRepository.save_run()` currently writes only its JSON payload and a few
  identity fields. `conversation_totals()` sums the unwritten columns.
- Product knowledge is read from JSON and cached in the process. Prompts are
  assembled in `backend/agent/policy.py`. There is no standalone few-shot data
  source. The normal model-based extraction call currently sends the latest text
  without including the preceding messages passed to the extractor; repairing
  model context is a separate quality task, not a prerequisite for this storage fix.

## Repair rounds and outcome

All four rounds below have been implemented. Rounds 1–3 were verified with the
backend suite and the 20-case offline backend evaluation using both repository
backends. Round 4's 28-scenario offline and live-model results are recorded in
[`evals/results.md`](../../evals/results.md); that report is dated 2026-09-23 and
describes the state at that run. No new paid-model run was made for this repair.

| Round | Work | Acceptance gate | Result |
| --- | --- | --- | --- |
| 1. State round trip | Persist pending/collected fields and score-history evidence with backward-compatible defaults. | Restart, confirmation, cancellation, and structured-answer checks pass. | Complete |
| 2. SQLite consistency | Persist run metrics and atomically save all durable records for one turn. | Totals and rollback/restart checks pass; existing databases remain readable. | Complete |
| 3. Real-path coverage | Add codec, SQLite reopen, HTTP multi-turn, and dual-backend evaluation coverage. | 339 backend tests and both 20-case / 67-turn backend evaluations passed on 2026-09-25. | Complete |
| 4. Eval-contract alignment | Align the 28-scenario suite with the active customer flow, response shape, and disclaimer. | The dated evaluation report records 28/28 offline and 28/28 live-model scenarios passed. | Complete; historical run |

Model-context continuity was initially deferred by this plan and has since been
implemented separately; see [`conversation-memory-repair-plan.md`](conversation-memory-repair-plan.md).

## Safety and boundaries

- Do not change `main` or the frozen `docs/v0.0/api/interface-v1.md`.
  Work on `salespilot-v1.0` and make no remote Git
  mutation or local commit without a separate request.
- Do not alter the customer/admin visibility boundary. The customer endpoint must
  not expose score, state, run telemetry, or internal evidence.
- Keep API keys in environment configuration, never in SQLite, knowledge JSON,
  prompts, test fixtures, or reports.
- Agent-run prompt/output content may contain customer text. Preserve the existing
  telemetry switch and avoid writing secrets or sensitive health details into
  long-lived logs. Privacy hardening beyond this repair needs its own decision.
- The user approved implementation and test creation for the repair. Do not
  commit or push without a separate request.

## Deferred decisions

1. Few-shot examples: select only after a stable, measurable failure category is
   observed; keep examples distinct from held-out eval cases.
2. Message/history normalization: consider only when the JSON-payload approach
   becomes measurably inadequate for incremental reads or storage volume.

Model-context continuity was implemented separately. Live-provider summary
accuracy remains unmeasured and must not be inferred from source-ID checks.
