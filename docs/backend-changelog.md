# Backend changelog

Record of what changed in each update to the Python backend: `salespilot/**`,
`tests/**`, `run.py`, `requirements.txt`.

> **This file is updated only on explicit instruction from the repository owner.**
>
> Completing a code change does not authorise an entry here. If work seems worth
> recording, finish the work and report that a changelog entry is pending
> authorisation. Do not create, edit, or append entries otherwise.

This is the backend counterpart to `docs/frontend-changelog.md` and follows the
same gate. It is a record of *what changed*; the API specification itself lives in
`docs/backend-contract.md`, and the status table at the bottom of that file remains
the signal the frontend keys its capability detection against.

## How to write an entry

One entry per authorised update. Newest first. Keep it factual and short — what
changed, why, and anything a reviewer or demo operator needs to know.

```markdown
## <YYYY-MM-DD> — <short title>

**Scope:** api | engine | detection | knowledge | storage | models | providers | tooling
**Contract items:** <Part B item numbers from docs/backend-contract.md, if applicable>

### Changed
- <what changed, in behavioural terms>

### Fixed
- <bug, how it manifested, and why it was not visible before>

### Contract impact
- <additive / breaking / none — and what a frontend must do, if anything>

### Verified
- <what was actually run, and what could not be verified>

### Known issues
- <anything left broken or deliberately deferred>
```

---

## Entries

## 2026-09-22 — `backend/` rebuild, phases P0–P2: skeleton, domain, deterministic kernel

**Scope:** models, engine, tooling (all under the new `backend/` package)
**Contract items:** 10, 11, 13 modelled — **none on the wire yet**

Second entry of the day. The first records the last work done on `salespilot/`; this
one begins its replacement. Plan, reasoning and per-phase acceptance criteria:
`docs/backend-plan.md`.

### Changed

- **`salespilot/` is frozen and will be discarded.** It receives no further changes
  of any kind, including the prompt-drift fix previously planned for it: a codebase
  scheduled for deletion is not worth renovating. `backend/` is the only forward
  track and the only implementation of `docs/api/interface-v1.md` §5. The frozen tree
  still runs, and its 80 tests still pass, but it is no longer a maintained
  deliverable.
- **`backend/` rebuilt from an empty directory** into nine packages with a one-way
  import direction: `domain <- kernel <- services -> agent -> providers`, and
  `api -> services`. The copy of `salespilot/` it started from was deleted entirely
  rather than patched.
- **`domain/` is now the single source of truth for every wire string.** The
  structured-output schemas the model will be given, the tool signatures it may call
  and the API serialisers all derive from `domain/enums.py` instead of restating it.
  This is the structural fix for the defect described under *Fixed* below.
- **Three message axes instead of one overloaded field** (`interface-v1.md` §1.2,
  §5.7, §5.8): `role` for which side of the conversation — now `"customer"` /
  `"business"`, with `"agent"` gone and no transitional alias — `author` for who
  wrote it, and `generation` for how it was produced. `generation: "template"` is what
  makes an offline reply distinguishable from a model reply.
- **`turns` became a read-only property** over `customer_message_count`
  (`interface-v1.md` §1.1). The wire keeps the name; no code inside the backend can
  use the misleading one to mutate state.
- **Opportunity scoring redesigned to two axes with a qualification gate**
  (gap register item 13). Fit and behaviour are scored separately, `product_potential`
  and `expansion` move to fit, engagement gains multiplicative recency decay, and
  `priority` is derived from the two axes as a matrix. `priority` keeps exactly its
  three existing values, so admin badge and count logic is unaffected.
- **The qualification gate has three levels and the machine can only reach the
  middle one.** It may raise a conversation to `held`; only a human sets
  `disqualified`, and only a human releases a hold. The design principle is not
  "judge accurately" — the judgement originates in a model and will sometimes be
  wrong — but "make being wrong cheap and reversible". A false hold costs a cooler
  reply and one click; it loses no lead and deletes nothing. Held is not ignored:
  complaints and explicit requests for a person still escalate.
- **`kernel/takeover.py` extracted.** The takeover freeze was a boolean threaded
  through a two-hundred-line method, consulted at two distant points and patched again
  at its end. It is now one module returning a decision that explains itself.
- **The kernel receives its inputs and never reaches out for them.**
  `scoring.score` takes an injected `now`; `hitl.evaluate` takes a `confidence_floor`
  defaulting to a kernel constant. `kernel` has no permission to import `config`. A
  business rule whose outcome depends on an environment variable the module fetched
  for itself cannot be reproduced from the stored record, which defeats the purpose of
  an auditable core.
- **Dependency added:** `pydantic-ai-slim[openai]==2.46.0`, confined to
  `backend/agent/` by an enforced test. `domain/` and `kernel/` remain
  standard-library only and run with none of it installed.

### Fixed

- **Advertising traffic was scored as though it were buying.** Measured on the frozen
  build: spam that never mentions insurance reached 66 MEDIUM *and consumed a human
  escalation*; spam that borrowed insurance vocabulary reached **96 HIGH and outranked
  a genuine customer at 82**, with the assistant replying "Great to hear you're
  interested!" to it. The cause was mechanical — *buy* in "buy cheap watches" matched
  the Purchase signal, and price words let the product classifier guess a plan. The
  model only rewarded activity and penalised nothing, so the noisiest conversation won.
  In the rebuild both cases are held, carry a fit of zero and sit at LOW, absent from
  the queue. The mechanism is not that the arithmetic suppresses spam: **genuineness
  is a fit question**, so a conversation that is not a sales enquiry has no fit
  whatever it does.
- **The engagement dimension had no notion of time.** It was
  `min(12, 3 + 2 * message_count)` — a pure counter, so a conversation abandoned a
  month ago kept full marks while being named "Engagement & Urgency". Recency now
  multiplies the behaviour axis from 100% down to a 35% floor. Fit is not decayed:
  silence does not make a corporate account less valuable, it makes the evidence that
  they are buying weaker.
- **The state machine imported the extraction layer.** `salespilot/engine/state.py`
  did `from ..detection.signals import SignalDetector` so it could run two text
  heuristics itself, putting extraction logic inside the deterministic core. Both are
  observations, so they now arrive on `Detection` as `cancellation` and
  `postponement`, and the kernel only reads them. The architecture test rejects the
  inversion if it returns.
- **Impossible messages were representable.** A human representative's reply had to
  be recorded as `role: "agent"`, which read as a contradiction, and nothing prevented
  a message claiming a person's words were template-generated. `Message` now rejects
  every combination outside the five documented ones at construction.
- **The architecture test had a blind spot, and it was returning a green it had not
  earned.** `from .. import config` places the target in the node's `names` rather
  than its `module`, so that import form was invisible to the check. Fixed, and it
  immediately caught a real violation — `kernel/hitl.py` reading `config` — which
  produced the injection rule above. Recorded prominently because a partial guarantee
  of a layering rule is worse than none: it suppresses the suspicion that would
  otherwise prompt a manual look.

### Contract impact

**None yet.** No HTTP endpoint exists in `backend/` at this point, so nothing has
changed for either frontend. Items 10, 11 and 13 are marked *modelled / decided, not
yet on the wire* in the gap register for precisely this reason; only `Shipped` means
an adapter can rely on a field arriving.

When the surface does land, the frontend-visible changes will be: `role: "business"`
replacing `"agent"` (breaking, one line per adapter plus the admin mock fixtures),
plus the additive `author`, `generation`, `customer_message_count`, `fit`, `behaviour`
and `qualification` fields. `priority` keeps its three values throughout.

Two gaps were raised against the shared contract during this work: **item 12**, an
incremental cursor for the admin conversation read, since `interface-v1.md` §5.6
covers only the customer surface while the admin side is the one that polls the full
profile; and **item 13** above.

### Verified

- `py -3 -m pytest backend/tests -q` → **101 passed**.
- `py -3 -m pytest tests -q` → **80 passed**, the frozen build untouched.
- Test-driven throughout: every phase's tests were written and seen to fail before
  the code existed. The owner granted a standing Rule 2 exception scoped to this plan.
- `P0-1` … `P0-4` from the frozen build are restated as assertions rather than
  trusted: a price concern does not escalate; a competitor mention alone does not
  escalate; a discount request escalates *as a negotiation* with a reason containing
  none of "medical", "underwriting" or "compliance"; takeover freezes the state and
  the score floor, lets the customer's own withdrawal and conversion through, and
  forces human handling on later messages.
- The layering rules of `docs/backend-plan.md` §4 are executable, not advisory.
- **Not verified:** anything above the kernel. There is no agent runtime, no
  persistence, no HTTP surface and no model call yet. Those are phases P3 to P7.

### Known issues

- Some P2 acceptance checks were walked by hand rather than asserted. Converting them
  is the first claim on the half day gained in P2.
- The scoring weights, the two band tables and the decay curve are judgement, not
  evidence. With no historical conversion data the model cannot be validated against
  close rates, so the claim is not that it predicts better — it is that three
  structural failure modes the industry convention names are gone, and that every
  dimension is individually inspectable.
- The memory and cost analysis in `docs/backend-plan.md` §12 is a first pass and says
  so. Deferred: a summarisation tier between the transcript window and the profile, a
  telemetry retention policy, and measurement against a real provider rather than
  estimates.
- `main_concern` and `concerns` remain model-authored free text and are therefore a
  prompt-injection path. Guards are specified in §12.1 but not yet implemented; they
  land with the agent shell in P3.

---

## 2026-09-22 — Message idempotency, request validation, knowledge base relocation

**Scope:** api, storage, models, tooling
**Contract items:** Part B item 1 (shipped)

### Fixed

- `POST /api/messages` is now idempotent when the caller supplies
  `client_message_id`. Previously every call appended the message, incremented
  `opportunity.turns`, and re-ran the state machine and scoring, so a retry after
  a network timeout duplicated the message and corrupted the opportunity. Because
  the engagement dimension is `min(12, 3 + 2 * turns)` in `engine/scoring.py`, the
  opportunity value score rose for an event that never happened — silently, with
  no exception and nothing unusual in the log. Measured on a duplicate `"hello"`:
  `turns` 1 → 2, engagement 5 → 7, total score 13 → 30. A customer could be
  promoted toward HIGH priority by a flaky connection.
- Removed unreachable code in `PATCH /api/cases/{id}` that assigned to
  `repo._cases`, the in-memory repository's private state. `BaseRepository`
  already provides a default `update_case`, so the `hasattr` guard in front of it
  was always true and the fallback never executed. The same always-true guard was
  removed from `agent/assistant.py`.

### Changed

- `POST /api/messages` accepts an optional `client_message_id`. The first
  successful call stores its serialised response as a receipt keyed on
  `(opportunity_id, client_message_id)`; a replay returns that response verbatim
  without running the pipeline or touching state. Omitting the field preserves the
  previous behaviour exactly.
- `BaseRepository` gained `get_message_receipt` / `save_message_receipt` with an
  in-process default. `SqliteRepository` overrides them with a `message_receipts`
  table so deduplication survives a server restart. The table carries a
  `schema_version` column, but receipts are still replayed across versions
  deliberately: returning a slightly older response shape is safer than re-running
  the pipeline and inflating `turns` again.
- `Message` gained `client_message_id`, persisted in the SQLite messages payload
  and echoed in `opportunity.messages[]`. Rows written before this change load
  with `None` rather than failing.
- `PATCH /api/cases/{id}` now validates its body with a `CaseStatusUpdate`
  request model instead of parsing an untyped `dict`.
- `data/knowledge_base.json` moved to `salespilot/data/knowledge_base.json`, since
  it is backend-owned data. `logs/` and `runtime/` stay at the repository root
  because they are generated rather than shipped. `Dockerfile` uses `COPY . .` and
  needed no change. Stale `data/` references were synced in `AGENTS.md`,
  `.kiro/steering/tech.md`, `docs/backend-handoff.md` and `README.md`.

### Contract impact

Additive. Every new field is optional and every existing field keeps its name,
type and meaning. `role` remains the closed set `"customer"` / `"agent"`.

One behavioural change: `PATCH /api/cases/{id}` with a missing or malformed body
now returns `422` instead of `400`. An unknown status *value* still returns `400`.

Frontends can remove the degradation described in Part B item 1 — retry is safe.

### Verified

- `py -3 -m pytest tests/ -v` and `py -3 -m unittest discover -s tests -v`: green.
- All five acceptance criteria in Part B item 1, plus response-level deep equality
  on replay, receipt survival across a simulated restart, and the full status-code
  matrix for `PATCH /api/cases/{id}`. Encoded as `P0-5` and `U1`-extension tests in
  `tests/test_api.py`.
- The `P0-5` tests were mutation-checked against a repository that never returns a
  receipt, confirming they fail when idempotency is absent.
- `py -3 run.py --demo` produces unchanged scores and product detection after the
  knowledge base move.
- **Not verified:** behaviour under two genuinely concurrent requests carrying the
  same key. There is no lock, so both could enter the pipeline. Accepted for a
  single-user demo and noted in the endpoint comment.

### Known issues

- The engagement dimension of the opportunity value score is a pure message
  count: no time decay, a 12-point floor unrelated to buying intent, an urgency
  bonus that only inspects the current turn (inconsistent with the `best_intent`
  high-water mark used elsewhere), and a `3 + 2 * turns` baseline whose lower bound
  of 3 is unreachable. Idempotency closes the external trigger but not the
  underlying coupling between the score and a mutable counter. Deferred to the
  architecture review, not changed here.
- Part B items 2-5 remain outstanding. Item 4 (human representative reply) looks
  less like a missing endpoint than a product decision: the original design
  treats takeover as a channel switch, which is why no write path for a human
  message exists.
