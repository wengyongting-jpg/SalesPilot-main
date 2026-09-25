# Backend changelog

Record of what changed in each update to the Python backend: `backend/**`,
`backend/tests/**`, and the frozen `salespilot/**`, `tests/**`, `run.py`,
`requirements.txt`.

> **This file is updated only on explicit instruction from the repository owner.**
>
> Completing a code change does not authorise an entry here. If work seems worth
> recording, finish the work and report that a changelog entry is pending
> authorisation. Do not create, edit, or append entries otherwise.

This is the backend counterpart to `docs/v0.0/frontend/frontend-changelog.md` and follows the
same gate. It is a record of *what changed*; the API specification itself lives in
`docs/v0.0/backend/backend-contract.md`, and the status table at the bottom of that file remains
the signal the frontend keys its capability detection against.

## How to write an entry

One entry per authorised update. Newest first. Keep it factual and short — what
changed, why, and anything a reviewer or demo operator needs to know.

```markdown
## <YYYY-MM-DD> — <short title>

**Scope:** api | engine | detection | knowledge | storage | models | providers | tooling
**Contract items:** <Part B item numbers from docs/v0.0/backend/backend-contract.md, if applicable>

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

## 2026-09-22 — `backend/` rebuild, phases P3–P7: agent, observability, storage, API, model access

**Scope:** api, engine, detection, knowledge, storage, models, providers, tooling — all
under `backend/`
**Contract items:** 1–15. Every one now **on the wire**, where the previous entry had
10, 11 and 13 modelled only.

Third entry of the day and the one that makes the rebuild usable. `backend/` now serves
both surfaces, persists to SQLite, calls a real model when one is configured, and runs
a complete conversation when none is. `salespilot/` remains frozen and untouched.

### Changed

- **`agent/` — a real agent loop, not a fixed pipeline.** Two model-led segments with
  the deterministic kernel between them, and five read-only tools the model may choose
  to call: `lookup_product_fact`, `compare_products`, `list_products`,
  `conversation_summary`, `request_human_handoff`. The composing segment continues the
  observing segment's conversation rather than starting a second one, so the model
  writing the reply remembers what it just looked up.
- **The kernel is not a tool.** It runs unconditionally, exactly once, in a fixed
  order, as plain calls in `services/conversation.py`. That is what makes "exactly
  once, in this order" a property of the code rather than of a framework's
  configuration — it holds identically when no model is configured, and it still holds
  when a provider times out halfway through a run.
- **Extraction and reply are peers, not a path and a fallback.** Each has a
  rule-based/template implementation and a model implementation behind one protocol.
  Delegation between them is always *declared*: the outcome says it degraded and why.
  The frozen build's untyped `except Exception:` fallback is what let its two paths
  drift apart unnoticed.
- **Framework adopted: Pydantic AI** (`pydantic-ai-slim[openai]`). Chosen for
  enum-typed structured output, which removes the drift defect class by construction,
  and because `TestModel` exercises the whole loop offline. Confined to `agent/` by an
  executable rule.
- **`observability/` — per-run records.** Ordered steps with kind, duration, status and
  `detail`; model calls with tokens and cost; the tool calls the model chose;
  violations. Rendered to the terminal per run and served on the admin tier.
- **`storage/` — two repositories behind one protocol**, in-memory and SQLite, with
  messages, score history and state history in their own tables so a cursor read and a
  bounded history read do not have to load a whole conversation.
- **`api/` — 13 routes split by visibility tier.** The boundary is a *type*: the
  customer response model has no field in which sales intelligence could be placed, so
  leaking a score is impossible rather than discouraged.
- **Model access.** `providers/` resolves configuration to a `ProviderSpec` and imports
  nothing third-party; `agent/model_factory.py` is the only module that constructs a
  model. Either outcome is first-class — with no key the whole pipeline completes on
  the offline peers and says why, in plain language, at startup and in every run.
- **`--configure`** — interactive setup. Takes the key without echoing it, finds which
  endpoint accepts it, reads that endpoint's real model list so the name is chosen
  rather than guessed, verifies with one live request, then updates `.env` in place,
  preserving comments and unmanaged settings.
- **`--demo`** — the whole pipeline in a terminal, no server. Prints each turn's
  intent, signals, state transition, both score axes decomposed, qualification,
  priority, next best action, every tool the model chose, and the run's tokens and
  cost. The two web surfaces show the customer's side and the sales queue; neither
  shows what happened in between.
- **`--probe`** distinguishes *cannot reach the endpoint* from *the endpoint said no*,
  because the first is the network or the URL and the second is the credential or the
  account. It speaks HTTP directly over the standard library, so it tests the endpoint
  rather than the framework and still works when the framework is absent.
- **CORS** for configured loopback origins (item 15), from configuration, no wildcard,
  `allow_credentials` off. This was the last thing preventing either frontend from
  working in a browser rather than only from Node.

### Fixed

- **Cost accounting reported two paid model calls as a known zero.** `record_llm_call`
  existed from P4 and was thoroughly tested, but nothing on the live path ever called
  it, so a run through a real provider reported `llm_call_count: 0`,
  `total_tokens: 0` and `cost: {"amount": 0.0, "pricing_known": true}`. The last field
  is the damaging one: it does not say *unmeasured*, it asserts the price is known and
  the spend was precisely nothing. Live for the whole of P4 to P6.

  *Why nothing caught it.* The recorder was exercised without its caller, and the only
  service-level assertion about `llm_call_count` ran on the offline path — where zero
  is the correct answer. The fixture could not fail. `TestModel` reports token usage,
  so the defect was catchable with no network, no key and no fake server.
- **Taking a case over did not set `human_takeover`** (item 14). `CaseService.transition`
  released the opportunity on `CLOSED` but never claimed it on `TAKEN_OVER`, so the
  console could `PATCH` a case to `Taken Over`, receive 200, and then have its rep
  reply refused with "take over first" — said to the operator who had just done that.
  A test named `test_taking_over_does_not_clear_the_flag` asserted the flag was true
  and passed, because escalation had already set it; the defect only appears on the
  *second* takeover, after a close has released it.
- **Product inheritance read the assistant's own words.** The overview reply names all
  four plans, so scanning recent history for a product picked one out of the
  assistant's message. A budget-conscious individual was reclassified as corporate,
  quadrupling the deal size.
- **The handover reply arrived with a price card attached.** Customer-visible facts are
  now one list, used both to prompt the composer and as the returned `facts`, so the
  reply and the cards cannot disagree.
- **Priority ignored Dormant/Lost.** A lapsed conversation could outrank a live one.
  Now capped at `MEDIUM` — it may be worth reviving, just not the next call.
- **`FIT_A_MIN` raised 70 → 75.** One question naming a mid-tier plan scored exactly 70
  and reached `HIGH`, which devalues the band.
- **Behaviour decay made multiplicative.** As an additive recency dimension it could
  not move a band: forty days of silence still came out `HIGH`.
- **Extraction prompt drift, structurally.** The frozen build offered the model
  `"medical_question"`, which the domain rejects, and only 7 of 11 signals — making
  four escalation triggers unreachable whenever a model was configured. Schemas are now
  generated from the enums, so the two cannot disagree.
- **Redirected output could crash on the customer's own words.** Piped stdout takes the
  locale encoding, `cp936` on the development machine, and traces echo customer text;
  a character that encoding cannot represent raised `UnicodeEncodeError` from inside
  the logger. Now UTF-8 with `errors="replace"`.
- Several defects in this work's *own* new code, found by running it rather than by
  reading it: `--demo` read `run["total_tokens"]` and `step["notes"]`, neither of which
  exists, and defaulted — printing "0 tokens" for a run that had spent them, and
  reducing every degradation to the bare word "degraded". A `.get(key, 0)` on a key
  that was never there is not a default, it is a fabrication.

### Contract impact

- **`docs/v0.0/backend/backend-contract.md` items 1–15 are all shipped.** Items 14 and 15 closed
  last, both P0. The register also had two items numbered 13; CORS is now 15.
- **`docs/v0.0/api/interface-v1.md` is now `Status: frozen`.** v1 is closed to both tracks,
  corrections included: anything found wrong in it is recorded in
  `docs/v0.0/backend/backend-contract.md` and specified in a v2, never patched in place.
- **It was verified line by line against a running server *before* the freeze**, which
  is the order that mattered — after freezing, a correction costs a v2. Seven errors,
  all corrected first, full list in that file's §7. The two worst would have made a
  frontend behave incorrectly rather than merely be uninformed: the header instructed
  frontends to treat every `PROPOSED` field as absent, which by then meant discarding
  the entire live contract; and §4.3's `HIGH (score ≥ 80)` threshold disagrees with the
  served `priority` on two of four seeded conversations, demoting the genuine
  high-intent customers to `MEDIUM`. §5.9 now specifies the two-axis derivation and
  marks `total` display-only.
- **Paths moved.** Staff endpoints are namespaced under `/api/admin/*` and the customer
  transcript is `/api/conversations/{id}`. Adapters written against the frozen build's
  paths need retargeting; §5 of the interface is the target.
- **Wire values.** `role` is `customer` | `business`. Messages carry `author` and
  `generation`. `cost` carries `pricing_known`. Runs carry `violations`, steps carry
  `detail`.
- **`?since=` takes a message id or an ISO-8601 timestamp, never an index.** An index
  returns 400.

### Verified

```powershell
py -3 -m pytest backend/tests -q     # 421 passed, 91 subtests
py -3 -m pytest tests -q             # 80 passed — frozen build, untouched
py -3 -m backend --probe
py -3 -m backend --demo
py -3 -m backend --serve --seed
```

- 13 routes exercised under real uvicorn, and again through `TestClient`.
- The model path proved end to end against a **local OpenAI-compatible server** built
  for the purpose: two HTTP requests per message matching the two segments,
  `generation: "llm"`, real token counts, and cost of `$0.0000069` for
  2 × (11 + 3) tokens at `gpt-4o-mini` rates — checked against the published rates by
  hand.
- Both degradation columns walked: no key → `generation: "template"` throughout, runs
  `degraded` with the reason on the step that degraded, `/health` `degraded: true`;
  with a model → `"llm"`, `status: "ok"`.
- The two most consequential fixes were confirmed by **deliberately reintroducing the
  defect** and watching the new assertions fail: four for cost accounting, one for the
  takeover round trip.
- Customer-tier payload re-checked for leakage against the full forbidden list from
  interface-v1 §2: nothing.

### Known issues

- **The organiser's gateway was never available**, so the OpenAI-compatible path is
  verified against a local endpoint and against the published protocol, not against
  theirs. If their endpoint speaks something else, `providers/resolve.py` plus
  `agent/model_factory.py` are the only files that change.
- **No authentication anywhere.** Unchanged accepted demo limitation, not an oversight.
  CORS is scoped to loopback for the same reason a wildcard was refused: nothing is
  protected today, and a wildcard would become a real hole the moment that changes.
- **Offline mode logs a WARNING for every message**, because the run genuinely is
  degraded. In the default mode that is every message, which buries real warnings.
  Splitting "degraded because no model is configured" (informational) from "degraded
  because a configured model failed" (a warning) is proposed and not yet done.
- **Memory and cost model has room to improve** — `docs/v0.0/backend/backend-plan.md` §12. Three
  quadratic paths are guarded rather than eliminated.
- **Several acceptance checks are still walked by hand** rather than asserted,
  `docs/v0.0/backend/backend-plan.md` §11.
- **`main_concern` prompt-injection hardening is partial.** `policy.sanitise_concern`
  and `policy.data_section` are in use; the rest of §12.1 is not implemented.
- **The frontends have not been run against `backend/` in a browser.** The backend no
  longer prevents it — that was items 14 and 15 — but the step itself belongs to the
  frontend track.

---

## 2026-09-22 — `backend/` rebuild, phases P0–P2: skeleton, domain, deterministic kernel

**Scope:** models, engine, tooling (all under the new `backend/` package)
**Contract items:** 10, 11, 13 modelled — **none on the wire yet**

Second entry of the day. The first records the last work done on `salespilot/`; this
one begins its replacement. Plan, reasoning and per-phase acceptance criteria:
`docs/v0.0/backend/backend-plan.md`.

### Changed

- **`salespilot/` is frozen and will be discarded.** It receives no further changes
  of any kind, including the prompt-drift fix previously planned for it: a codebase
  scheduled for deletion is not worth renovating. `backend/` is the only forward
  track and the only implementation of `docs/v0.0/api/interface-v1.md` §5. The frozen tree
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
- The layering rules of `docs/v0.0/backend/backend-plan.md` §4 are executable, not advisory.
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
- The memory and cost analysis in `docs/v0.0/backend/backend-plan.md` §12 is a first pass and says
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
  `docs/v0.0/conventions/tech.md`, `docs/v0.0/backend/backend-handoff.md` and `README.md`.

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
