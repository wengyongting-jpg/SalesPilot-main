# SalesPilot persistence and evaluation repair plan

Status: **proposed for review; not implemented**

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

The existing `messages`, `score_history`, and `state_history` tables are declared in
`schema.sql` but the current repository reads and writes these histories inside the
opportunity JSON payload. Leave the unused tables in place for now. Do not migrate or
delete user data as part of this repair. Reconsider normalization only if actual
conversation size or incremental-query performance requires it.

## Verified starting point

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

## Repair rounds

| Round | Work | Acceptance gate | Estimate |
| --- | --- | --- | --- |
| 1. State round trip | Extend `storage/codec.py` to serialize and restore the four pending/collected fields and score-history evidence. Use backwards-compatible defaults for existing payloads. | A handoff offer, restart, and typed `Confirm` create one case; cancellation and structured-question answers also survive a restart. | 30–45 min |
| 2. SQLite consistency | Align the columns written by `SqliteRepository` with those queried, especially agent-run tokens, cost, and pricing-known status. Make the writes for one completed customer turn atomic across opportunity, case, run, and optional receipt, or document and resolve any repository-interface constraint before changing the transaction boundary. | Totals match the saved agent-run payload; a simulated write failure cannot leave a half-completed handoff or replay receipt. Existing databases remain readable. | 60–90 min |
| 3. Real-path coverage | With explicit approval to add test code, add codec round-trip, SQLite reopen, and real-HTTP multi-turn confirmation checks. Make the 20-case eval runner selectable between memory and SQLite without altering case labels. | Both storage modes pass the 20 offline cases; backend and frontend suites do not regress; no paid model call is needed for this gate. | 45–75 min |
| 4. Eval-contract alignment | Review the separate top-level 28-scenario suite against the current confirmation flow, customer API response shape, and approved disclaimer. Correct obsolete assertions while retaining useful adversarial and lifecycle cases. | Failures identify product behavior rather than an outdated protocol or a broken assertion. Run the paid-model suite only after the deterministic gates pass, under its existing call and cost limits. | 45–75 min |

Estimated implementation and local verification: **2.25–3.5 hours for rounds 1–3**,
or **approximately 3–5 hours including round 4**. Gateway latency can extend the
final paid-model run. These are estimates, not deadlines. Each round is reported
separately and must pass its gate before the next result is described as complete.

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
- This document authorizes no code or test creation by itself. The repository's
  `AGENTS.md` requires separate user consent before adding tests. Documentation
  updates outside this dedicated plan also require their own authorization.

## Deferred decisions

1. Model-context continuity: decide what bounded history and approved business
   state should actually be sent to model extraction, then evaluate its effect
   separately from persistence changes.
2. Few-shot examples: select only after a stable, measurable failure category is
   observed; keep examples distinct from held-out eval cases.
3. Message/history normalization: consider only when the JSON-payload approach
   becomes measurably inadequate for incremental reads or storage volume.
