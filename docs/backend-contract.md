# Backend API contract

Audience: the backend team, and any frontend developer integrating against the
SalesPilot REST API.

> **Precedence changed on 2026-09-22.** The authoritative contract is now
> **[`docs/api/interface-v1.md`](api/interface-v1.md)**, a shared file both tracks
> edit. Where that file and this one disagree about a shape, **that file wins**.
>
> Read in this order:
> 1. **[`docs/backend-handoff.md`](backend-handoff.md)** — ownership, priorities,
>    what must not change.
> 2. **[`docs/api/interface-v1.md`](api/interface-v1.md)** — the contract, the
>    naming rules, the visibility tiers, the communication topology.
> 3. This file — the gap register, with a test and acceptance criteria per item.

This document has two halves:

- **Part A — the frozen build's API. Historical.** It describes `salespilot/`, not what
  is served. The live contract is
  **[`docs/api/interface-v1.md`](api/interface-v1.md) §5**, which is frozen as of
  2026-09-22 and self-contained. Part A carries no authority: where it disagrees with
  the interface document, it is wrong. Add no schema detail here.

  It was going to be deleted once interface v1 was frozen. Keeping it instead, because
  Part B below describes every change *relative* to it, and deleting it would leave
  fifteen items comparing the present against nothing.
- **Part B — the gap register.** Gaps the frontends hit, each with the reason, the
  shape, a test and acceptance criteria. **All fifteen are now shipped** — see the
  status table at the end of this file, which remains the signal a frontend keys its
  capability detection against.

Interface v1 is frozen, so this file is where a further change or a correction is
raised first; it is then specified in an `interface-v2.md` rather than edited into v1.

Terminology: this document covers only the **backend REST API** consumed by the
frontends. The separate OpenAI-compatible *provider API* the backend uses to
reach an LLM is internal and out of scope here.

---

## Part A — Current API

> **Part A describes the frozen `salespilot/` build and is historical.** Its paths are
> not the ones now served. The live surface is `backend/`, which namespaces the staff
> endpoints under `/api/admin/*` so the visibility tiers are a routing fact rather than
> a client convention — `/api/opportunities` became `/api/admin/opportunities`,
> `/api/cases` became `/api/admin/cases`, and the customer transcript moved to
> `/api/conversations/{id}`.
>
> For the surface to integrate against, read
> [`api/interface-v1.md`](api/interface-v1.md) §5, or start the server and read
> `/docs`. Part A is kept because the gap register below refers back to it when
> describing what changed.

Base URL in development: `http://127.0.0.1:8000`. For the frozen build:

```powershell
py -3 run.py --serve --seed          # frozen; the live one is `py -3 -m backend`
```

No authentication exists on any endpoint. Anyone who can reach the server can
read or mutate any customer's conversation by guessing a `customer_id`. This is a
known and accepted limitation of the demo; it is recorded here so it is not
mistaken for an oversight.

### Endpoint summary

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/` | Legacy console (frozen) |
| GET | `/health` | Liveness + counts |
| POST | `/api/messages` | Process one customer message through the full pipeline |
| GET | `/api/opportunities` | List all opportunity profiles |
| GET | `/api/opportunities/{id}` | One opportunity profile with history |
| DELETE | `/api/opportunities/{id}` | Reset a conversation (idempotent) |
| GET | `/api/cases` | List HITL cases |
| PATCH | `/api/cases/{id}` | Transition case status |
| GET | `/api/dashboard` | Queue text + opportunity list |
| GET | `/api/analytics` | Aggregate sales analytics |
| POST | `/api/seed` | Seed demo data (idempotent) |

### POST /api/messages

The main endpoint. Runs the 12-step agent pipeline and returns the reply together
with the full decision context.

Request:

```json
{
  "customer_id": "C-2001",
  "customer_name": "Sam",
  "text": "How much does CareSure Plus cost?",
  "client_message_id": "c-8f2a1b40"
}
```

`customer_name` is required. `customer_id` defaults to `""` (the backend then
generates one). `text` must be at least 1 character. `client_message_id` is
optional and makes the call idempotent — see Part B item 1, now shipped.

Response, verified from a live call:

```json
{
  "reply": "string — the customer-facing message",
  "opportunity": {
    "opportunity_id": "C-2001",
    "customer_name": "Sam",
    "state": "Potential Interest",
    "product": "plus",
    "signals": [],
    "signal_history": [],
    "main_concern": null,
    "competitive_risk": false,
    "churn_risk": false,
    "compliance_risk": false,
    "expansion": [],
    "priority": "LOW",
    "final_score": 45,
    "score_history": [
      { "ts": "ISO-8601", "score": 45, "state": "Potential Interest", "trigger": "message(rule)" }
    ],
    "state_history": [
      { "ts": "ISO-8601", "from": "Cold Lead", "to": "Potential Interest", "reason": "Clear insurance need identified" }
    ],
    "human_takeover": false,
    "human_intervention_required": false,
    "turns": 1,
    "messages": [
      { "ts": "ISO-8601", "role": "customer", "text": "...", "client_message_id": "c-8f2a1b40" },
      { "ts": "ISO-8601", "role": "agent", "text": "...", "client_message_id": null }
    ]
  },
  "detection": {
    "intent": "price",
    "product": "plus",
    "signals": [],
    "concerns": [],
    "restricted": false
  },
  "retrieval": {
    "facts": ["string", "..."],
    "confidence": 0.9,
    "product": "plus"
  },
  "score": {
    "purchase_intent": 18,
    "purchase_readiness": 7,
    "product_potential": 15,
    "expansion": 0,
    "engagement": 5,
    "total": 45,
    "priority": "LOW"
  },
  "state_change": "Cold Lead -> Potential Interest (Clear insurance need identified)",
  "next_best_action": {
    "action": "Continue nurturing and clarify needs",
    "reason": "Early interest — nurture and guide to the right plan",
    "priority": "LOW",
    "human_intervention_required": false
  },
  "case": null,
  "extraction_source": "rule"
}
```

`case` is `null` unless this message triggered or updated a HITL escalation.
`extraction_source` is `"rule"` offline and `"llm"` when an LLM extractor is
configured.

Note for frontends: `opportunity.messages` already contains the full transcript
including the agent reply just generated. A client can either append the reply
locally or reconcile against this array.

Each message now also carries `client_message_id`. It echoes the key the client
sent for that message, and is `null` for agent replies and for customer messages
sent without one. Reconciliation can therefore match on the key directly instead
of matching by position from the end of the array. `role` remains a deliberately
closed set of `"customer"` and `"agent"`.

### Enumerations

Opportunity states (exactly six, in funnel order):

```
Cold Lead
Potential Interest
Evaluation & Hesitation
High Intent
Closed / Active Customer
Dormant / Lost
```

Priority bands: `HIGH` (score ≥ 80), `MEDIUM` (≥ 50), `LOW` (< 50).

Signals (11):

```
Purchase
Purchase Preparation
Hesitation
Competitive
Expansion: Family
Expansion: Corporate
Human Request
Compliance Risk
Negotiation
Conversion
Withdrawal
```

Products: `essential`, `family`, `plus`, `corporate`, `unknown`.

Case status is serialised in title case: `"Open"`, `"Taken Over"`, `"Closed"`.
Clients should normalise before comparing.

### GET /api/opportunities/{id}

Returns the same `opportunity` object shown above. Returns `404` with
`{"detail": "Opportunity not found"}` when the id is unknown.

Returns the **entire** message array every call — there is no incremental cursor.
See Part B item 3.

### DELETE /api/opportunities/{id}

Resets a conversation. Idempotent; deleting an unknown id is a no-op.

```json
{ "deleted": true, "opportunity_id": "C-2001" }
```

### GET /api/cases

```json
{
  "count": 1,
  "items": [
    {
      "id": "H-10FC2C",
      "opportunity_id": "C-1024",
      "customer_name": "Sarah",
      "state": "High Intent",
      "product": "plus",
      "reason": "High purchase intent with competitive comparison — recommend human sales intervention",
      "summary": "Customer is in state ... Signals: ... Main concern: ...",
      "recommended_action": "Human sales intervention: address competitive risk",
      "status": "Open",
      "created_at": "ISO-8601"
    }
  ]
}
```

### PATCH /api/cases/{id}

Body: `{ "status": "TAKEN_OVER" }`. Accepts enum names (`OPEN`, `TAKEN_OVER`,
`CLOSED`) or serialised values (`"Open"`, `"Taken Over"`, `"Closed"`); spaces and
hyphens are normalised to underscores. Returns the updated case object.

Transitioning to `CLOSED` also clears `human_takeover` and
`human_intervention_required` on the linked opportunity, which resumes autonomous
AI selling on the next customer message. Returns `404` for an unknown case id and
`400` for an invalid status.

The body is now validated by a request model rather than parsed by hand. A missing
body, or a body without a non-empty `status` string, returns `422` with FastAPI's
structured error array. An unrecognised status *value* still returns `400`. The
previous implementation returned `400` for a missing body; that was the only
behavioural change, and it aligns the endpoint with `POST /api/messages`.

### GET /api/dashboard

```json
{
  "text": "pre-rendered text dashboard",
  "total": 3,
  "take_over": 1,
  "items": [ /* array of opportunity objects */ ]
}
```

The admin console should use `items` and ignore `text` (it is CLI output).

### GET /api/analytics

```json
{
  "total_opportunities": 3,
  "by_priority": { "HIGH": 1, "MEDIUM": 1, "LOW": 1 },
  "by_state": { "Cold Lead": 0, "Potential Interest": 1, "...": 0 },
  "by_product": { "corporate": 1, "plus": 2 },
  "funnel": [ { "state": "Cold Lead", "count": 0 } ],
  "signals": { "Purchase": 2, "Hesitation": 1 },
  "average_score": 63.7,
  "escalated_opportunities": 1,
  "human_cases_total": 2,
  "human_cases_open": 1,
  "competitive_risks": 1,
  "conversion_rate_of_closed": 0.5,
  "converted": 1,
  "lost": 1
}
```

### POST /api/seed

Idempotent. Seeds three scripted conversations (Sarah, Michael, ABC Corp). If
opportunities already exist it returns `{"seeded": false, "reason": "..."}`
without duplicating.

### GET /health

```json
{ "status": "ok", "opportunities": 3, "open_cases": 1 }
```

### Error format

FastAPI default: `{"detail": "<message>"}` with the relevant status code.
Validation failures return `422` with FastAPI's structured error array. There is
no application-specific error envelope. Frontends should not depend on one, and
should treat any non-2xx as a transport-level failure with a generic user-facing
message.

---

## Part B — Required changes

Ordered by priority. Each item is independent and can ship separately.

### 1. Message idempotency — P0, correctness bug — **SHIPPED 2026-09-22**

> **Shipped.** All five acceptance criteria below were verified. The implemented
> shape matches what was requested; the notes under *As implemented* record two
> details the original specification left open.

**Current behaviour.** `POST /api/messages` is not idempotent. Each call appends
the message, increments `opportunity.turns`, and re-runs the state machine and
scoring. A client retry after a network timeout therefore duplicates the message
*and* corrupts the opportunity: `turns` is inflated, and because the engagement
dimension is computed as `min(12, 3 + 2 * turns)` (see
`salespilot/engine/scoring.py`), the opportunity value score rises for a reason
that never happened. This makes retry-on-failure unsafe, so the frontend cannot
offer a correct "tap to retry".

**Expected behaviour.** Accept an optional client-generated idempotency key. When
a key is replayed for the same `customer_id`, return the original result without
mutating state.

```json
{
  "customer_id": "C-2001",
  "customer_name": "Sam",
  "text": "How much does CareSure Plus cost?",
  "client_message_id": "c-8f2a1b40"
}
```

The key should be stored alongside the message so deduplication survives a
restart when SQLite is in use. Omitting the field preserves today's behaviour.

**Test.**

```bash
# Same key twice
curl -s -X POST http://127.0.0.1:8000/api/messages \
  -H "Content-Type: application/json" \
  -d '{"customer_id":"C-9001","customer_name":"Idem","text":"hello","client_message_id":"k1"}' \
  | python -c "import sys,json; d=json.load(sys.stdin); print(d['opportunity']['turns'], len(d['opportunity']['messages']))"

curl -s -X POST http://127.0.0.1:8000/api/messages \
  -H "Content-Type: application/json" \
  -d '{"customer_id":"C-9001","customer_name":"Idem","text":"hello","client_message_id":"k1"}' \
  | python -c "import sys,json; d=json.load(sys.stdin); print(d['opportunity']['turns'], len(d['opportunity']['messages']))"
```

**Acceptance criteria.**

1. Both calls print the same `turns` and the same message count.
2. Both responses have an identical `score.total` and `state_change`.
3. A third call with a *different* key and the same text does increment `turns`.
4. Omitting `client_message_id` behaves exactly as today.
5. No new entry is appended to `score_history` on the replayed call.

**Frontend degradation until shipped.** The composer generates and sends
`client_message_id` already. Failed sends surface a retry affordance, but retry is
disabled with an explanatory tooltip when the backend has not advertised
idempotency support. **This degradation can now be removed** — retry is safe.

**As implemented.**

*Replay semantics.* The first successful call stores its serialised response as a
receipt keyed on `(opportunity_id, client_message_id)`. A replay returns that
stored response **verbatim** and touches no state. This is replay semantics on
purpose: the answer means "here is the response to that request", not "here is the
current state". The consequence is that a replay issued after other messages have
been processed returns a snapshot that predates them. In a real retry flow this
cannot happen — a client retries precisely because it received no response, so it
has not sent anything newer — and the next poll of
`GET /api/opportunities/{id}` reconciles regardless. The alternative, re-serialising
the live opportunity into a stored decision context, was rejected because it can
emit a response whose `score.total` and `opportunity.final_score` disagree.

*Blank `customer_id`.* Deduplication is scoped to the opportunity, so a request
with `customer_id: ""` (where the backend generates the id) cannot match an
earlier receipt and always runs the pipeline. The receipt is still written under
the generated id, so any later replay that supplies that id is deduplicated
normally. A client that wants idempotency on the very first message of a
conversation must send its own `customer_id`.

*Storage.* `Repository` keeps receipts in process memory. `SqliteRepository`
persists them in a `message_receipts` table, so deduplication survives an API
server restart. Receipts carry a `schema_version` column: they are still replayed
across versions on purpose, because returning a slightly older response shape is
safer than re-running the pipeline and inflating `turns` again.

*Not handled.* Two genuinely concurrent requests carrying the same key are not
serialised — there is no lock — so both could enter the pipeline. Left as-is for a
single-user demo, and noted in the endpoint's comment.

*Additive side effect.* `opportunity.messages[].client_message_id` was added, as
described in Part A.

### 2. Quick replies in the response — P1

**Current behaviour.** `reply` is plain text only. There is no structured
suggestion payload, so the chat cannot render quick-reply chips without inventing
them client-side, which would put business logic in the frontend and contradict
the project's separation rule.

**Expected behaviour.** Add an optional array to the `POST /api/messages`
response. Values are short, customer-safe prompts derived from the deterministic
decision layer — not LLM-generated free text.

```json
{
  "reply": "...",
  "quick_replies": [
    { "id": "qr_compare_plans", "label": "Compare plans" },
    { "id": "qr_how_to_apply", "label": "How do I apply?" }
  ]
}
```

Constraints: at most 3 items; `label` at most 24 characters; empty array or
omitted field both mean "render no chips"; chips must never be offered while
`opportunity.human_takeover` is true, since the AI must not steer the
conversation once a human owns the case.

**Test.**

```bash
curl -s -X POST http://127.0.0.1:8000/api/messages \
  -H "Content-Type: application/json" \
  -d '{"customer_id":"C-9002","customer_name":"QR","text":"I want to learn about health insurance"}' \
  | python -m json.tool | grep -A6 quick_replies
```

**Acceptance criteria.**

1. A cold-lead opening message returns 1–3 quick replies.
2. Labels are ≤ 24 characters and contain no premium figures or personalised
   advice.
3. When `human_takeover` is true, `quick_replies` is empty.
4. `id` values are stable across identical conversation states, so they can be
   logged and tested.
5. Existing clients that ignore the field continue to work unchanged.

**Frontend degradation until shipped.** No chips render. The composer alone is
fully sufficient to drive the demo.

### 3. Incremental message fetch — P2

**Current behaviour.** `GET /api/opportunities/{id}` returns the whole profile
including every message. Polling it re-transfers the entire transcript each time.

**Expected behaviour.** A focused endpoint with a cursor.

```
GET /api/opportunities/{id}/messages?since=<ISO-8601 timestamp or message id>
```

```json
{ "opportunity_id": "C-1024", "messages": [ { "id": "...", "ts": "...", "role": "agent", "text": "..." } ] }
```

Omitting `since` returns the full transcript.

**Test.**

```bash
curl -s "http://127.0.0.1:8000/api/opportunities/C-1024/messages" | python -c "import sys,json; print(len(json.load(sys.stdin)['messages']))"
curl -s "http://127.0.0.1:8000/api/opportunities/C-1024/messages?since=2099-01-01T00:00:00" | python -c "import sys,json; print(len(json.load(sys.stdin)['messages']))"
```

**Acceptance criteria.**

1. Without `since`, the count matches `GET /api/opportunities/{id}`.
2. With a future `since`, the array is empty.
3. With the timestamp of the last known message, only newer messages return.
4. An unknown id returns 404; a malformed `since` returns 400.

**Frontend degradation until shipped.** The adapter polls
`GET /api/opportunities/{id}` and diffs locally by index. Correct, just wasteful.

### 4. Human representative reply — P2

**Current behaviour.** There is no way for a human to post a message into a
conversation. `POST /api/messages` is customer-input-only and always runs the full
AI pipeline. Consequently, once a case is taken over, the representative cannot
actually reply, and live polling has nothing new to discover. This is the single
change that makes real-time updates meaningful.

It is also worth noting that the legacy console's chat-panel "TAKE OVER" button
(`executeTakeover()` in `salespilot/static/app.js`) only toggles CSS classes and
never calls the API, even though `PATCH /api/cases/{id}` exists. Any new admin
surface must call the real endpoint.

**Expected behaviour.**

```
POST /api/opportunities/{id}/rep-reply
{ "text": "Hi Sarah, this is Alex from CareSure...", "rep_name": "Alex", "client_message_id": "r-1a2b" }
```

Appends an agent-role message attributed to a human, **without** running
detection, scoring, state transition, or HITL evaluation. Should be rejected with
`409` when the opportunity is not under human takeover, so the endpoint cannot be
used to bypass the AI pipeline.

**Test.**

```bash
# Expect 409 when not under takeover
curl -s -o /dev/null -w "%{http_code}\n" -X POST \
  http://127.0.0.1:8000/api/opportunities/C-9003/rep-reply \
  -H "Content-Type: application/json" -d '{"text":"hi","rep_name":"Alex"}'
```

**Acceptance criteria.**

1. Under takeover, the message appears in `opportunity.messages` with a role that
   distinguishes it from AI output.
2. `turns`, `score`, `state`, `signals` and `score_history` are unchanged.
3. Not under takeover, returns 409 and appends nothing.
4. The customer chat, polling, receives the message within one poll interval.

**Frontend degradation until shipped.** The admin console's case view is
read-only with a disabled reply box explaining that rep replies are not yet
supported. The customer app polls but only ever observes AI replies.

### 5. Message identity and delivery status — P3, optional

**Current behaviour.** `Message` in `salespilot/models.py` carries only
`role`, `text`, `ts`. No id, no status.

**Expected behaviour.** Add a stable `id` per message, and optionally a
`status` field if the backend ever gains asynchronous delivery.

This is deliberately low priority. The customer app maps tick states to real
client-observable events rather than faking them:

| Tick state | Real event |
| --- | --- |
| Clock | POST in flight |
| Single tick | HTTP 2xx received |
| Double blue tick | Agent reply rendered |

That mapping is honest without any backend change, so this item only matters if
true server-side delivery receipts are wanted later.

**Acceptance criteria.** Every message in `opportunity.messages` carries a unique
`id` that is stable across repeated `GET` calls, and clients keyed on `id` do not
re-render existing messages.

### 6. Visibility tiers by namespace — P0

Specified in `docs/api/interface-v1.md` §2 and §5.1.

**Current behaviour.** `POST /api/messages` returns the full decision context —
`score`, `priority`, `signals`, `state`, `next_best_action`, `case` — to whoever
calls it, and the customer frontend discards it at the adapter boundary. The
customer app also calls `GET /api/opportunities/{id}` for history, which returns
the same intelligence.

This is not a boundary. The data reaches the customer's browser and is visible in
developer tools; only client-side discipline hides it. Once item 8 adds model
prompts, token counts and costs, it becomes untenable: prompt text and spend data
cannot be shipped to a customer's browser on the promise that the client will not
render them.

**Expected behaviour.** Separate the surfaces so the customer response has **no
shape** for sensitive data — absent, not filtered.

| Surface | Endpoints |
| --- | --- |
| Customer | `POST /api/messages`, `GET /api/conversations/{id}`, `DELETE /api/conversations/{id}` |
| Admin | `/api/admin/*` — opportunities with intelligence, cases, dashboard, analytics, agent runs |

Existing paths may remain as admin aliases during migration. The
customer-safe / not-safe split per field is tabulated in interface §2.

Authentication remains out of scope. This is a shape separation, not access
control; doing it now means adding auth later is configuration rather than
redesign.

**Test.**

```bash
# No sensitive key may appear in a customer-surface response
curl -s -X POST http://127.0.0.1:8000/api/messages \
  -H "Content-Type: application/json" \
  -d '{"customer_id":"C-9101","customer_name":"Tier","text":"How much does CareSure Plus cost?"}' \
  | python -c "import sys,json; d=json.load(sys.stdin); \
banned=['score','priority','signals','state','next_best_action','case','detection']; \
print('LEAK:',[k for k in banned if k in d] or 'none')"
```

**Acceptance criteria.**

1. The customer response contains none of `score`, `priority`, `signals`,
   `state`, `next_best_action`, `case`, `detection`, or `retrieval.confidence`.
2. It still contains `reply`, approved knowledge-base facts, `quick_replies` when
   implemented, and the `client_message_id` echo.
3. `GET /api/conversations/{id}` returns only `ts`, `role`, `author`, `text`,
   `client_message_id` per message.
4. An admin endpoint returns the full intelligence for the same conversation.
5. A customer-surface response never contains agent-run telemetry under any
   query parameter or header.

### 7. The `author` field — P1

Specified in `docs/api/interface-v1.md` §1.2 and §5.2.

**Current behaviour.** `role` is `"customer"` \| `"agent"`. The backend's own
comment in `models.py` notes that who *authored* an agent-side message, AI versus
a human representative, "is a separate axis and is not encoded here". So an AI
reply and a human reply are indistinguishable.

**Expected behaviour.** Add `author`: `"ai"` \| `"human"` \| `"system"`, and
`null` for customer messages. `role` is unchanged. `author` deliberately excludes
`"customer"` so that `role` is not derivable from it and the two cannot drift.

Additive: absent means `"ai"` for agent-side messages.

**Test.**

```bash
curl -s http://127.0.0.1:8000/api/opportunities/C-1024 \
  | python -c "import sys,json; ms=json.load(sys.stdin)['messages']; \
print([(m['role'], m.get('author')) for m in ms])"
```

**Acceptance criteria.**

1. Every customer message has `role: "customer"` and `author: null`.
2. Every AI reply has `role: "business"` (see item 11) and `author: "ai"`.
3. `author` never takes the value `"customer"`.
4. Existing clients that ignore `author` behave exactly as before.

### 8. Agent run telemetry — P1

Specified in `docs/api/interface-v1.md` §5.3, which carries the full payload
shape.

**Current behaviour.** Nothing is captured. `providers/llm.py` discards
`response.usage` entirely; there is no timing, no token count, no cost, and no
record of which pipeline steps ran. `extraction_source` is the only observability
in the response, and a silent fallback from LLM extraction to rules is invisible
beyond it.

**Expected behaviour.** Persist one agent run per processed message and expose it
on the admin surface:

```
GET /api/admin/agent-runs?opportunity_id=&client_message_id=&limit=
GET /api/admin/agent-runs/{run_id}
```

Carrying: duration, status (`ok` / `degraded` / `error`), the ordered steps with
per-step kind and duration, per-LLM-call model, token counts, cost, and input and
output content with character lengths, plus totals.

Three constraints that matter:

- **Cost is computed server-side.** The model name and price table belong in the
  backend; a frontend holding pricing would be business logic in the wrong layer.
- **`kind: "tool"` is reserved for model-selected calls and must stay unused**
  until a real tool-calling loop exists. Knowledge retrieval is
  `kind: "retrieval"`. Labelling a fixed pipeline step a tool call would
  reintroduce exactly the conflation interface §1 exists to prevent.
- **`input.content` / `output.content` are gated by a backend flag, off by
  default**, because prompts contain the customer's own words. `chars` is always
  present so a console can show size even when content is withheld.

**Test.**

```bash
curl -s -X POST http://127.0.0.1:8000/api/messages \
  -H "Content-Type: application/json" \
  -d '{"customer_id":"C-9102","customer_name":"Tel","text":"How much does CareSure Plus cost?","client_message_id":"c-tel-1"}' > /dev/null
curl -s "http://127.0.0.1:8000/api/admin/agent-runs?client_message_id=c-tel-1" \
  | python -m json.tool
```

**Acceptance criteria.**

1. A run exists for every processed message and is retrievable by
   `client_message_id`.
2. `totals.llm_call_count` is 0 with the stub provider and matches the real
   number of model invocations otherwise — counting extraction *and* response
   generation, not just one.
3. `tool_calls` is an empty array and `totals.tool_call_count` is 0.
4. When LLM extraction fails and rules take over, `status` is `"degraded"` and
   the failing step records it.
5. `cost.amount` is present whenever tokens were consumed, and absent with the
   stub provider rather than reported as 0.
6. With the content flag off, `input.chars` is present and `input.content` is
   absent.
7. Runs survive a server restart when SQLite is in use.
8. No agent-run data appears on any customer-surface response (ties to item 6).

### 9. Rename the `turns` counter — P2, semantics

Specified in `docs/api/interface-v1.md` §1.1.

**Current behaviour.** `opportunity.turns` counts **customer messages**. It is
routinely read as "agent turns", which it is not. The backend's own changelog
already describes the engagement dimension as "a pure message count".

Five distinct countable things are at stake: `customer_message_count`,
`agent_run_count`, `agent_step_count`, `llm_call_count`, `tool_call_count`. Today
only the first exists, under a name that implies a different one.

**Expected behaviour.** Add `customer_message_count` alongside `turns` as the
preferred name. Keep `turns` for backward compatibility. Do not change its value:
the engagement dimension is `min(12, 3 + 2 * turns)`, so redefining it silently
changes every score.

**Acceptance criteria.**

1. `customer_message_count` is present and always equal to `turns`.
2. No new field named `turns`, or documentation describing `turns` as agent
   turns, is introduced anywhere.
3. Score output is byte-identical to before the change.

### 10. The `generation` field — P1, raised by the backend

Specified in `docs/api/interface-v1.md` §5.7.

**Current behaviour.** When no model is configured, or when a model call fails,
the backend silently produces the reply from a deterministic template and returns
it in exactly the same shape as a model-generated reply. Nothing in the payload
distinguishes the two. `extraction_source` reveals the extraction half only, and
nothing at all reveals that the *wording* came from a template.

**Expected behaviour.** Add `generation` to every message: `"llm"`, `"template"`,
`"human"`, or `null` for customer messages. `role` answers which side, `author`
answers who, `generation` answers how — three axes, per the §1 rule that one field
must carry one meaning. Absent means `"llm"` for agent-side messages, so an
existing client is unaffected.

**Acceptance criteria.**

1. Every agent-side message carries a non-null `generation`.
2. With no model configured, an end-to-end conversation produces
   `generation: "template"` on every agent message, and the corresponding agent
   run reports `status: "degraded"`.
3. With a model configured and healthy, agent messages report `"llm"`.
4. A representative reply reports `"human"`.
5. A client that ignores the field behaves exactly as before.

**Frontend degradation until shipped.** Business-side messages are treated as
`"llm"`. The customer app shows no offline badge; the admin console cannot
distinguish a model reply from a template reply.

### 11. Rename `role: "agent"` to `role: "business"` — P1, breaking

Specified in `docs/api/interface-v1.md` §1.2 and §5.8.

**Current behaviour.** `role` is `"customer"` or `"agent"`. The second value reads
as "AI agent", so a message written by a human representative — which is
`role: "agent"`, `author: "human"` — looks like a contradiction and forces a reader
to consult a second field to undo a confusion the first one created. This is the
same one-field-two-meanings defect as items 7 and 9.

**Expected behaviour.** `role` is `"customer"` or `"business"`. The value names the
party, not the author: a human, an AI and a system notice are all the business
speaking. No transitional alias — a closed set with a deprecated member is not a
closed set.

**Acceptance criteria.**

1. No response contains `"role": "agent"`.
2. Every message carries `"customer"` or `"business"`.
3. A rep reply serialises as `role: "business"`, `author: "human"`,
   `generation: "human"`.

**Migration cost, measured before deciding.** Neither real frontend adapter is
implemented. `frontend/customer/js/store.js` derives its own `direction` axis and
never reads `role`. `frontend/admin/` normalises to its own `origin` axis. The only
occurrences of `'agent'` in shipped frontend code are mock fixtures in
`frontend/admin/js/gateway/mock.js`. No view code changes.

### 12. Incremental read on the admin surface — P2, raised by the backend

`docs/api/interface-v1.md` §5.6 proposes an incremental cursor for the **customer**
surface. The admin surface has none, and it is the side that polls the full profile
and carries the most fields.

**Current behaviour.** `GET /api/opportunities/{id}` returns the complete
`messages`, `score_history` and `state_history`. All three grow with conversation
length, and the console polls. Linear per poll therefore compounds to quadratic over
a session.

**Expected behaviour.** `?since=` on the admin conversation read, matching the
customer-surface cursor, plus an explicit bound or page on the two history arrays.

**Acceptance criteria.**

1. Without `since`, the payload matches today's content.
2. With the timestamp or id of the last known message, only newer entries return.
3. The history arrays are bounded by a documented default and a query parameter.
4. A malformed cursor returns 400; an unknown id returns 404.

**Frontend degradation until shipped.** The console polls the full profile and diffs
locally. Correct, and wasteful in proportion to transcript length.

### 13. Two-axis opportunity scoring and a qualification gate — P1, raised by the backend

**Current behaviour.** One flat 100-point score built from five behavioural
dimensions. No fit axis, no gate, no negative scoring, no decay. Measured against
the frozen build:

| Conversation | Score | Priority |
| --- | --- | --- |
| Advertising spam that never mentions insurance | 66 | MEDIUM — and it consumed a human escalation |
| Advertising spam that borrows insurance vocabulary | **96** | **HIGH** |
| A genuine high-intent customer | 82 | HIGH |

Spam outranks a real customer, and the assistant replies "Great to hear you're
interested!" to it. The cause is mechanical: *buy* in "buy cheap watches" matches the
Purchase signal, and price words let the product classifier guess a plan.

There is no authoritative standard for lead scoring, but there is a consistent
industry convention with four parts — fit and behaviour as **separate** axes, fit
gating behaviour, negative scoring, and score decay. The current model implements
one of the four.

**Expected behaviour.**

- **Fit axis** — genuineness, whether the need is one CareSure sells, product
  potential and expansion breadth. `product_potential` and `expansion` move here:
  they describe how much the opportunity is worth, not how warm it is.
- **Behaviour axis** — purchase intent, readiness, and engagement with recency decay.
- **Qualification gate**, three levels, where the machine can only reach the middle
  one:

  | Level | Who can set it | Effect |
  | --- | --- | --- |
  | Qualified | default | Normal selling |
  | **Held** | **the machine may** | The assistant stops advancing the sale — no quotes, no pushing, still answers politely. Absent from the sales queue. Appears in a separate held list, released by one human click. Scored but not ranked |
  | Disqualified | **a human only** | Removed |

  Held requires a model observation **and** a deterministic corroboration (no genuine
  insurance need observed anywhere in the conversation). Held is not ignored: abuse
  and complaints still escalate to a person. The reason for a hold is visible in
  telemetry, never an opaque boolean.

- `priority` keeps exactly three values, `HIGH` / `MEDIUM` / `LOW`. Only its
  derivation changes, from a single threshold to a two-axis lookup, so badge and
  count logic is unaffected. `fit`, `behaviour` and `qualification` are new
  **admin-tier** fields.

**Acceptance criteria.**

1. Advertising spam, with or without insurance vocabulary, does not reach the sales
   queue and does not outrank a genuine customer.
2. A genuine customer is never disqualified by the machine; the worst case is held,
   and a single action releases it.
3. Abuse or a complaint still escalates to a human even while held.
4. `priority` still serialises as one of the three existing values.
5. An opportunity with no activity for a long period scores lower than an identical
   recent one — decay is observable.
6. The reason for a hold is present in the agent run record.

**Honest limitation.** With no historical conversion data the new weights remain
judgement rather than evidence, and the model cannot be validated against close
rates. The claim is not that it predicts better; it is that it removes three
structural failure modes the industry convention names, and that every dimension is
individually inspectable on the admin surface.

**Frontend degradation until shipped.** Priority and score render as today.

### 15. CORS on the API — P0, blocks all browser integration — **SHIPPED 2026-09-22**

> Renumbered from 13, which had been used twice: this item and the scoring one above
> both claimed it. References elsewhere to "item 13, CORS" mean this section.
>
> **Shipped.** All six acceptance criteria verified, and asserted in
> `backend/tests/test_api.py::TestBrowserOriginsArePermitted`. Implemented as
> `_allow_development_origins` in `backend/api/app.py`, driven by
> `config.CORS_ORIGINS`.
>
> *As implemented*, two details the specification left open:
>
> 1. **`OPTIONS` is listed explicitly** in `allow_methods`, and the default origin list
>    covers **port 5500 as well as 8123** — that is the VS Code Live Server default, and
>    a frontend opened that way would otherwise be blocked with a message that looks
>    like a backend fault.
> 2. **`allow_headers=["Content-Type"]` produces a wider echo than it reads like.**
>    Starlette adds the CORS-safelisted request headers, so the response advertises
>    `Accept, Accept-Language, Content-Language, Content-Type`. That is the
>    specification's intent — those three are permitted on a cross-origin request with
>    or without a header — but the value is not literally what was written, and a
>    frontend asserting on the exact string would be surprised.
>
> An unknown origin is refused rather than silently allowed: the preflight returns
> **400** with no `Access-Control-Allow-Origin` header. Worth stating because a
> wildcard would satisfy every positive assertion in the list and is precisely what
> this item rules out.

**Current behaviour** *(before this shipped)*. The API sends no
`Access-Control-Allow-Origin` header, and
`backend/api/app.py` deliberately serves no static files — correctly, since the
two apps under `frontend/` replace the legacy console.

The consequence is that the apps and the API are always on different origins. In
development the frontends are served by `py -3 -m http.server 8123` from
`frontend/`, and the API listens on `8000`. A browser therefore refuses every
`fetch` from the console or the chat to the API, before the request reaches the
backend at all.

Verified on 2026-09-22 against a live `py -3 -m backend --serve --seed`: the
response headers are `content-length`, `content-type`, `date`, `server` — no CORS
header of any kind.

This is not a frontend workaround away. A static file server cannot add the
header to someone else's response, and proxying would mean introducing a
dev-server dependency, which the frontend's no-dependency rule forbids.

**What this does and does not block.** The adapters are written and verified
against the live API from Node, where no same-origin policy applies: the customer
adapter passes 17 checks and the admin adapter 27, covering idempotent replay,
the two-axis score, `generation`, rep-reply's 409 gate, cursor errors and the
agent-run shape. So the *mapping* is proven. What is blocked is the last step —
the same code running in a browser tab.

**Expected behaviour.** Permit the development origins. A single middleware:

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,   # e.g. ["http://127.0.0.1:8123", "http://localhost:8123"]
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type"],
)
```

Driven by configuration rather than hard-coded, and defaulting to the development
origins only. `allow_credentials` is not needed — there is no authentication
anywhere — so it should stay off, and `allow_origins=["*"]` should be avoided even
though nothing is protected, because it would set a habit that becomes a real
hole the moment auth exists.

**Test.**

```bash
# A preflight must be answered, and the actual request must carry the header.
curl -s -i -X OPTIONS http://127.0.0.1:8000/api/messages \
  -H "Origin: http://127.0.0.1:8123" \
  -H "Access-Control-Request-Method: POST" \
  -H "Access-Control-Request-Headers: content-type" | head -20

curl -s -i http://127.0.0.1:8000/health \
  -H "Origin: http://127.0.0.1:8123" | grep -i access-control-allow-origin
```

**Acceptance criteria.**

1. A preflight `OPTIONS` to `/api/messages` from `http://127.0.0.1:8123` returns
   2xx and lists `POST` in `Access-Control-Allow-Methods` and `content-type` in
   `Access-Control-Allow-Headers`.
2. `GET /health` with that `Origin` returns `Access-Control-Allow-Origin` echoing
   it.
3. `PATCH` and `DELETE` are permitted, since the console transitions cases and the
   chat resets conversations.
4. An origin outside the configured list is **not** granted the header.
5. The allowed origins come from configuration, and the default covers only
   loopback development origins.
6. `allow_credentials` remains off.

### 14. Taking a case over does not set `human_takeover` — P0, breaks the console's main workflow — **SHIPPED 2026-09-22**

> **Shipped.** All five acceptance criteria verified, asserted in
> `backend/tests/test_services.py::TestCaseService`. `CaseService.transition` now
> claims the opportunity on `TAKEN_OVER`, symmetrically with the release it already did
> on `CLOSED`.
>
> *How it stayed hidden*, which is worth recording. `backend/` had a test called
> `test_taking_over_does_not_clear_the_flag` that asserted the flag was true after a
> takeover, and it passed — because escalation had already set it, so the transition
> could do nothing at all and the assertion still held. The defect only appears on the
> second takeover, after a close has released the flag, which is criterion 5 and was
> the one case not covered. The test has been renamed and the round trip added; the new
> one was confirmed to fail against the unfixed code.

**Current behaviour.** The flag and the case status move in only one direction.

Measured on 2026-09-22 against a live `py -3 -m backend --serve --seed`:

```
opportunity C-1024
  human_takeover before:            false
PATCH /api/admin/cases/H-710C1B  {"status": "TAKEN_OVER"}   -> 200 "Taken Over"
  human_takeover after PATCH:       false            <-- unchanged
POST /api/admin/opportunities/C-1024/rep-reply          -> 409
  "C-1024 is not under human takeover; a representative reply is not accepted
   while the assistant is handling it"
```

Closing a case **does** clear `human_takeover` — that half is implemented and
verified. Taking one over does not set it. The two transitions are asymmetric.

**Why this blocks the admin console.** Its primary route is staff replying to a
customer, and the intended workflow is: see the escalated case, take it over, the
composer unlocks, reply. Step three cannot happen. The operator presses *Take
over*, the case correctly reads `Taken Over`, and the composer stays disabled
saying a takeover is required — which has just been done. The only way
`human_takeover` becomes true today is the HITL escalation inside the pipeline, so
once a case has been closed the conversation can never be taken over again through
the API.

This is not a frontend workaround away: the composer gate is `human_takeover`
because that is the same flag `rep-reply` enforces with its 409, and guessing
locally would produce a UI that offers a reply the server then refuses.

**Expected behaviour.** Make the transition symmetric with the one that already
works:

| Transition | `human_takeover` | `human_intervention_required` |
| --- | --- | --- |
| → `TAKEN_OVER` | set **true** | leave as-is |
| → `CLOSED` | set **false** (already correct) | set false (already correct) |
| → `OPEN` | unchanged | unchanged |

Reopening deliberately does nothing, because an open case means the assistant is
still handling the conversation and nobody has claimed it.

**Test.**

```bash
CASE=$(curl -s http://127.0.0.1:8000/api/admin/cases | python -c "import sys,json; print(json.load(sys.stdin)['items'][0]['id'])")
OPP=$(curl -s http://127.0.0.1:8000/api/admin/cases | python -c "import sys,json; print(json.load(sys.stdin)['items'][0]['opportunity_id'])")

curl -s -X PATCH http://127.0.0.1:8000/api/admin/cases/$CASE \
  -H "Content-Type: application/json" -d '{"status":"TAKEN_OVER"}' > /dev/null

curl -s http://127.0.0.1:8000/api/admin/opportunities/$OPP \
  | python -c "import sys,json; print('human_takeover:', json.load(sys.stdin)['human_takeover'])"

# Must now be accepted rather than 409.
curl -s -o /dev/null -w "rep-reply: %{http_code}\n" -X POST \
  http://127.0.0.1:8000/api/admin/opportunities/$OPP/rep-reply \
  -H "Content-Type: application/json" -d '{"text":"hello","rep_name":"Alex"}'
```

**Acceptance criteria.**

1. After a transition to `TAKEN_OVER`, `human_takeover` on the linked opportunity
   is `true`.
2. `POST .../rep-reply` on that opportunity then returns 200, not 409.
3. After a transition to `CLOSED`, `human_takeover` is `false` and `rep-reply`
   returns 409 again. (Already true; this guards it.)
4. A transition to `OPEN` leaves the flag unchanged.
5. A conversation can be taken over, closed, and taken over again through the API
   alone, with no pipeline escalation in between.

**Frontend degradation until shipped.** The composer distinguishes the two cases
rather than repeating "take over first" at an operator who just did: when the
linked case reads `Taken Over` but the flag is still false, it names the
mismatch and points at this item. The workflow remains blocked — there is no
honest way to unblock it client-side.

---

## Change log for this contract

Keep this table current when Part B items land, so frontend adapters know what to
enable.

| Date | Item | Priority | Status |
| --- | --- | --- | --- |
| 2026-09-22 | 1. Message idempotency | P0 | **Shipped** — verified from the frontend |
| 2026-09-22 | 2. Quick replies | P1 | **Shipped** — verified, 3 chips, labels ≤ 24 chars |
| 2026-09-22 | 3. Incremental fetch | P2 | **Shipped** — `?since=` on the customer transcript |
| 2026-09-22 | 4. Rep reply | P0 | **Shipped** — verified, 409 when not under takeover |
| — | 5. Message id / status | P3 | Partly: ids shipped; no delivery status, and none needed |
| 2026-09-22 | 6. Visibility tiers | P0 | **Shipped** — customer reply leaks zero intelligence keys |
| 2026-09-22 | 7. `author` field | P1 | **Shipped** — plus `generation` and `rep_name` |
| 2026-09-22 | 8. Agent run telemetry | P1 | **Shipped** — steps, `detail`, totals, violations |
| 2026-09-22 | 9. Rename `turns` | P2 | **Shipped** — `customer_message_count`, alias retained |
| 2026-09-22 | 10. `generation` field | P1 | **Shipped** — `llm` / `template` / `human`, with `author` as a separate axis |
| 2026-09-22 | 11. `role: "business"` | P1 | **Shipped** — no transitional alias; a closed set with a deprecated member is not closed |
| 2026-09-22 | 12. Incremental admin read | P2 | **Shipped** — `?since=` and `?history_limit=` on the admin profile |
| 2026-09-22 | 13. Two-axis scoring + gate | P1 | **Shipped** — spam is held and absent from the queue; only a human disqualifies |
| 2026-09-22 | 14. Takeover sets `human_takeover` | **P0** | **Shipped** — the round trip works with no escalation in between |
| 2026-09-22 | 15. CORS on the API | **P0** | **Shipped** — loopback origins from configuration, no wildcard, credentials off |

Items 1–4 and 6–9 were verified from the frontend against a live
`py -3 -m backend --serve --seed` on 2026-09-22: 17 checks through the customer
adapter and 27 through the admin adapter. The two things that still blocked a
*browser* — item 15 (no CORS headers) and item 14 (takeover did not set the flag) —
shipped later the same day, so nothing on the backend side remains outstanding.

Two wire details differed from what this register originally proposed, and the
adapters follow the implementation rather than the proposal:

- **`role` is `"customer"` / `"business"`**, not `"customer"` / `"agent"`.
- **The score is two-axis** — fit and behaviour, each with its own total — and
  `score.total` is explicitly display-only. Ranking comes from `priority`, so the
  console orders the queue by priority and uses the score only to break ties.
Items 10 to 15 were listed here separately while the rebuild's HTTP surface did not
exist yet, in states such as "modelled, not yet on the wire". That distinction has
expired: every one of them is now served by an endpoint, so the single table above is
the only status list, and `Shipped` there means an adapter can rely on the field
arriving. Item 13's measured effect — advertising spam held and absent from the queue,
where it previously scored 96 and outranked a genuine customer at 82 — is recorded in
`docs/backend-plan.md` §9 under P2.

**Where items 2-15 are implemented.** In `backend/`, the rebuild. **`salespilot/`
is frozen as of 2026-09-22 and will be discarded once the rebuild lands** — it
receives no further changes of any kind, including the correctness fixes previously
planned for it. The reasoning is in `docs/backend-plan.md` §2: the frontend has
deliberately left both real adapters unimplemented pending a frozen interface v1, so
implementing the interface twice would buy nothing, and a codebase scheduled for
deletion is not worth renovating.

Consequence for the frontend: the integration target is `interface-v1.md` §5, not
§4. §4 documents the frozen build and is now historical.

Item 4 was raised from P2 to P0 on 2026-09-22: it now blocks the admin console's
primary route rather than a secondary feature. The backend has noted it is partly
a product decision, since the original design treats takeover as a channel switch.
