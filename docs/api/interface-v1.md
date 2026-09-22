# SalesPilot interface — v1

| | |
| --- | --- |
| **Version** | v1 |
| **Status** | **`frozen`** as of 2026-09-22 — **no further edits.** See *Change rules* below |
| **Ownership** | **Shared.** Backend and frontend both edit this file. |
| **Supersedes** | `docs/backend-contract.md` Part A (the schema reference) |
| **Companions** | `docs/backend-contract.md` (gap register) · `docs/backend-handoff.md` (ownership and coordination) |

This is the **authoritative** request/response contract between the Python
backend and the two frontends. Where any other document disagrees with this one
about a shape, this one wins.

**Change rules — this file is frozen.** No edit is permitted, by either track. A
change to the contract means creating `interface-v2.md`, pointing it back at this file,
and leaving this one exactly as it is. Only one version is `current` at a time; this
header says which.

That includes corrections. If something here turns out to be wrong, it does not get
fixed in place — record it in `docs/backend-contract.md` and specify the correction in
v2. The value of a frozen contract is that two tracks can build against the same words
without re-reading it; a file that is quietly corrected provides none of that, and the
correction is invisible to whoever already read it.

Frozen on 2026-09-22, after a line-by-line verification against a running
`py -3 -m backend --serve --seed`. That pass found seven errors, two of which would
have made a frontend behave incorrectly rather than merely be uninformed — the header
telling frontends to discard the live contract, and §4.3's priority rule demoting
genuine high-intent customers. All seven were corrected **before** the freeze; §7
records each one. Freezing first and discovering them afterwards would have meant
either an immediate v2 or a broken rule.

**Which half to read.** The two halves of this document have swapped meaning since it
was written, and reading the wrong one is now the most expensive mistake available:

| Section | What it is |
| --- | --- |
| **§5** | **The live contract. Integrate against this.** Every item in it is implemented and verified against the running `backend/`. |
| §4 | Historical: the frozen `salespilot/` build. Kept because §5 and the gap register describe changes relative to it. **Do not integrate against §4.** |

`PROPOSED` markers on §5 headings are spent and have been removed. The earlier
instruction here — that frontends must treat every `PROPOSED` field as absent and
degrade — would now mean discarding the entire live contract, so it is withdrawn.
Verified against a live `py -3 -m backend --serve --seed` on 2026-09-22; §7 records
what the verification changed.

---

## 1. Naming discipline

Two defects of the same class have already been found in this project: **one field
carrying two meanings.** They are recorded here because the cost is silent wrong
numbers, not an exception, and because more of them will be introduced unless the
distinction is written down.

### 1.1 The counting family — do not say "turns"

`opportunity.turns` counts **customer messages**. It does not count agent
execution. Five genuinely different things are countable, and conflating any two
of them produces a plausible-looking wrong number:

| Name | Meaning | Where it is served |
| --- | --- | --- |
| `customer_message_count` | How many messages the customer sent | On the opportunity and on each agent run. **This is what `turns` actually is** |
| `agent_run_count` | How many times the pipeline executed end to end | `run_count` on `GET /api/admin/opportunities/{id}/cost`. 1:1 with the above today, but a different concept |
| `agent_step_count` | Steps within one run | `totals.agent_step_count`. Eleven, in a fixed order — the kernel sequence |
| `llm_call_count` | Model invocations | `totals.llm_call_count`. 0 offline; 2 with a model, one per segment, plus one per tool round trip |
| `tool_call_count` | Tool calls the **model chose** to make | `totals.tool_call_count`, and the calls themselves in `tool_calls` |

Rules:

1. **`turns` is deprecated as a name.** It stays in the payload for backward
   compatibility, but new fields must use `customer_message_count`, and
   documentation must never describe `turns` as "agent turns".
2. **Never label knowledge retrieval a tool call.** Retrieval is a kernel step, not a
   model-selected tool; it is reported with `kind: "retrieval"` and must not be counted
   in `tool_call_count`. The distinction carries more weight now than when it was
   written: a real tool-calling loop exists, so `tool_calls` is genuinely populated and
   the number means something. Padding it with retrieval would overstate what the model
   actually decided to do, which is the one thing a run record is for.
3. **The score is no longer a function of a message counter.** This section used to name
   `min(12, 3 + 2 * turns)` as the engagement dimension and call it load-bearing. That
   formula is gone: engagement is now depth, urgency and recency on a behaviour axis
   that decays multiplicatively with silence, separate from a fit axis, and `priority`
   comes from a matrix over the two rather than a threshold on a total. See §5.9. The
   old formula is worth remembering for why it was replaced — being a pure counter with
   no notion of time, an idempotent replay incremented it and silently inflated the
   score, which is the defect that started the rebuild.

### 1.2 The authorship axis — `role` is not `author`

`role` answers *which side of the conversation*. It does not answer *who wrote
it*. An AI reply and a human representative's reply are both on the same side.

**`role: "agent"` is renamed to `role: "business"`.** The old value carried the
same defect this section exists to prevent: "agent" reads as "AI agent", so a
message written by a human representative under `role: "agent"` looks like a
contradiction, and a reader has to consult `author` to resolve a confusion that
the value itself created. `"business"` names the *party* and implies nothing about
who or how — a human, an AI and a system notice are all the business speaking. It
is also the conventional counterpart to "customer" in messaging-platform
vocabulary, so it will read naturally to anyone who has integrated one.

Rejected alternatives: `"assistant"` implies AI just as much as `"agent"` did, and
is actively wrong for a human reply. `"caresure"` couples the wire format to the
brand. `"staff"` implies a person. `"in"` / `"out"` is **viewer-relative** — the
customer's inbound is the admin's outbound — so it can be an internal axis inside
one app (the customer app already uses `direction` that way) but must never be the
shared wire contract.

| Field | Values | Applies to |
| --- | --- | --- |
| `role` | `"customer"` \| `"business"` | Every message. Closed set. |
| `author` | `"ai"` \| `"human"` \| `"system"` \| `null` | Business-side messages. `null` for customer messages. |
| `rep_name` | string \| `null` | Customer-safe display name when `author` is `"human"`; otherwise `null`. |
| `generation` | `"llm"` \| `"template"` \| `"human"` \| `null` | Business-side messages. See §5.7. |

`author` deliberately does **not** include `"customer"`. If it did, `role` would
be derivable from `author` and the two fields could drift apart. A frontend that
wants a single axis derives it:

```js
const authorAxis = message.role === 'customer' ? 'customer' : (message.author ?? 'ai');
```

This separation is what makes a human representative reply representable at all
(`role: "business"`, `author: "human"`) and is a prerequisite for the admin Inbox.

**Migration.** The rename is a breaking change to a value both frontends read, and
it is being made now precisely because the cost is currently near zero: neither
real adapter is written yet, the customer app never consumes `role` (it derives
`direction` internally), the admin app normalises to its own `origin` axis, and the
only occurrences of `"agent"` in shipped frontend code are mock fixtures. The
backend will emit **only** `"business"`; it will not dual-write the old value,
because a transitional alias on a closed set is how a closed set stops being
closed. See §5.8.

---

## 2. Visibility tiers

**The visibility boundary is enforced server-side by payload shape, not by client
discipline.**

The earlier design returned the full decision context — score, priority, signals,
state, next best action, case — to whoever called `POST /api/messages`, and relied
on the customer frontend to discard it. That is not a boundary: the data reaches
the customer's browser and is visible in developer tools. Once model prompts,
token counts and costs are added, it becomes unacceptable outright.

| Tier | Consumer | Rule |
| --- | --- | --- |
| **Customer** | `frontend/customer/` | The response **has no shape** for sensitive data. Not filtered — absent. |
| **Admin** | `frontend/admin/` | Full detail, including model telemetry. |

What is customer-safe, and what is not:

| Data | Customer | Reason |
| --- | --- | --- |
| `reply` text | yes | It is the message being sent to them |
| `facts` | yes | Approved knowledge-base content; product cards need it. **Not** `retrieval.facts` — this is the narrower list of what the assistant was permitted to use this turn, so a handover reply does not arrive with a price card attached |
| `retrieval.confidence` | **no** | Internal signal about retrieval quality |
| `quick_replies` | yes | Rendered as chips. Empty while `human_takeover` is true |
| `message` | yes | The reply as a message object: `id`, `ts`, `role`, `author`, `rep_name`, `generation`, `text`, `client_message_id` |
| `human_takeover` | yes | A customer may be told a person is handling the conversation; it changes what the UI should offer |
| `client_message_id` echo | yes | Needed to reconcile their own message |
| opportunity `state` | **no** | Internal sales journey position |
| `score` (any dimension) | **no** | Internal prioritisation |
| `priority` | **no** | Internal |
| `signals` | **no** | Internal assessment of the customer |
| `next_best_action` | **no** | Internal sales instruction |
| `case` internals | **no** | A customer may be told a human is taking over, never the escalation reason or recommended action |
| `agent_run` telemetry | **no** | Model, prompts, tokens, cost |

**Authentication is out of scope.** This is a single-user demo and no endpoint is
protected. The tiers are therefore a *shape* separation, not an access control.
Separating the shapes now means adding authentication later is a configuration
change rather than a redesign. Do not add a fake login to imply otherwise.

---

## 3. Communication topology

Two distinct planes. Conflating them is the same class of mistake as §1.

### Plane A — backend REST (the product path)

```
frontend/customer/  ──REST──▶  backend  ◀──REST──  frontend/admin/
```

Both frontends talk only to the backend and are **blind to each other**. This
mirrors reality: a customer on their own phone, a representative in an office.
Their only coordination medium is backend state.

Rules:

1. Neither frontend may assume the other is running.
2. **No browser-local channel between independently opened frontends.**
   `BroadcastChannel`, `localStorage` events and `SharedWorker` are all
   technically available and all forbidden here, because they would make a demo
   depend on coupling that does not exist in production.

### Plane B — in-console test harness (the development path)

```
frontend/admin/  ──iframe + postMessage──▶  frontend/customer/
```

The admin console's harness route embeds the **unmodified** customer app in an
iframe, so it is a real device rather than a replica. This plane exists only in
that route and never in production topology.

Rules:

1. Same-origin only. Both apps must be served from one origin, so the harness
   requires an HTTP server — which ES modules already require anyway.
2. `postMessage` uses an explicit target origin, never `*`. The receiver
   validates `event.origin`.
3. The payload is **small and non-sensitive**: a correlation id, a
   client-observed duration, a status. Telemetry is *not* routed through the
   customer app, because under §2 the customer app never receives it.
4. Plane B is for driving a test device and correlating telemetry. It must not
   become a way for the admin to influence a customer conversation in the product
   sense; that belongs to Plane A.

### Telemetry correlation

Because the customer app cannot see telemetry, the admin fetches it itself and
joins on a key both sides already know:

```
1. embedded customer  ──▶  POST /api/messages { client_message_id: "c-8f2a" }
                      ◀──  customer-safe response echoing "c-8f2a"
2. embedded customer  ──postMessage──▶  admin
                          { clientMessageId: "c-8f2a", durationMs: 1240, status: 200 }
3. admin  ──▶  GET /api/admin/agent-runs?client_message_id=c-8f2a
          ◀──  full agent run telemetry
4. admin renders the debug timeline
```

`client_message_id`, added for idempotency, doubles as the telemetry correlation
key. No new identifier is needed.

---

## 4. The frozen build's contract — historical

> **Do not integrate against this section.** It describes `salespilot/`, which is
> frozen and will be deleted. Its paths are not the ones served: the staff endpoints
> now live under `/api/admin/*` and the customer transcript under
> `/api/conversations/{id}`. The live contract is **§5**.
>
> Kept because §5 and the gap register describe changes *relative* to this, so deleting
> it would make both harder to read.

Verified against `salespilot/api/app.py`, `api/schemas.py` and `models.py` as of the
2026-09-22 refactor, before the rebuild replaced it.

Base URL in development: `http://127.0.0.1:8000`.

### 4.1 Endpoints

| Method | Path | Tier | Purpose |
| --- | --- | --- | --- |
| GET | `/health` | both | Liveness and counts |
| POST | `/api/messages` | customer | Process one customer message |
| GET | `/api/opportunities` | admin | List opportunity profiles |
| GET | `/api/opportunities/{id}` | admin | One profile with history |
| DELETE | `/api/opportunities/{id}` | both | Reset a conversation |
| GET | `/api/cases` | admin | List HITL cases |
| PATCH | `/api/cases/{id}` | admin | Transition case status |
| GET | `/api/dashboard` | admin | Queue text plus opportunity list |
| GET | `/api/analytics` | admin | Aggregate analytics |
| POST | `/api/seed` | admin | Seed demo data (idempotent) |
| GET | `/` | — | Legacy console (frozen) |

Today these endpoints are **not** tier-separated: `POST /api/messages` returns the
full decision context, and the customer app calls `GET /api/opportunities/{id}`
for history. §5.1 is the proposal that fixes this.

### 4.2 POST /api/messages

Request:

```json
{
  "customer_id": "C-2001",
  "customer_name": "Sam",
  "text": "How much does CareSure Plus cost?",
  "client_message_id": "c-8f2a1b40"
}
```

`customer_name` required. `customer_id` defaults to `""` (the server then
generates one). `text` minimum length 1. `client_message_id` optional.

**Idempotency is live.** Replaying a key for the same conversation returns the
stored response verbatim without re-running the pipeline or touching state.
Omitting the key preserves the original non-idempotent behaviour. Not safe under
two genuinely concurrent requests with the same key — there is no lock.

Response, complete:

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
      { "ts": "ISO-8601", "role": "agent",    "text": "...", "client_message_id": null }
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
    "facts": ["string", "…"],
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

Notes:

- `case` is `null` unless this message triggered or updated a HITL escalation.
  When present it carries `id`, `opportunity_id`, `customer_name`, `state`,
  `product`, `reason`, `summary`, `recommended_action`, `status`, `created_at`.
- `extraction_source` is `"rule"` offline and `"llm"` when an LLM extractor is
  configured. A silent fallback from LLM to rules is visible only here; §5.3
  gives it a proper status.
- `opportunity.messages` already contains the full transcript including the reply
  just generated. A client may append locally or reconcile against this array.
- `client_message_id` is `null` for agent replies and for customer messages sent
  without a key. Reconciliation should match on this key rather than by position
  from the end of the array.
- `turns` counts customer messages. See §1.1 before using it for anything.
- **Most of this payload is not customer-safe.** §2 tabulates which fields are,
  and §5.1 is the proposal that removes the rest from the customer surface
  entirely.

Other endpoints return the same `opportunity` object; `GET /api/opportunities`
wraps it as `{ count, items[] }`. `GET /api/dashboard` adds `text` (pre-rendered
CLI output, not for web use), `total` and `take_over`. `GET /api/analytics`
returns `total_opportunities`, `by_priority`, `by_state`, `by_product`, `funnel`,
`signals`, `average_score`, `escalated_opportunities`, `human_cases_total`,
`human_cases_open`, `competitive_risks`, `conversion_rate_of_closed`,
`converted`, `lost`. `GET /health` returns `status`, `opportunities`,
`open_cases`.

### 4.3 Enumerations

Opportunity states, exactly six, in funnel order:

```
Cold Lead
Potential Interest
Evaluation & Hesitation
High Intent
Closed / Active Customer
Dormant / Lost
```

Priority: `HIGH` (score ≥ 80), `MEDIUM` (≥ 50), `LOW` (< 50) — **in the frozen build
only. Do not apply this to the live API; it produces the wrong answer.** Priority is
now derived from a two-axis fit × behaviour matrix and `score.total` is display-only.
See §5.9. Measured on the seeded queue, the rule above disagrees with the served
`priority` on two of four conversations, and in the damaging direction: Sarah
(fit 73, behaviour 82, total 78) and ABC Pte Ltd (fit 80, behaviour 74, total 77) are
both served as `HIGH`, while the threshold above computes `MEDIUM` — demoting the two
genuine high-intent customers the product exists to surface.

Signals, 11, exact strings including the colon-space form:

```
Purchase · Purchase Preparation · Hesitation · Competitive
Expansion: Family · Expansion: Corporate · Human Request
Compliance Risk · Negotiation · Conversion · Withdrawal
```

Products: `essential`, `family`, `plus`, `corporate`, `unknown`.

Case status, serialised in title case: `"Open"`, `"Taken Over"`, `"Closed"`.
Writes accept enum names or serialised values; spaces and hyphens normalise to
underscores. Clients normalise before comparing.

Message `role`: `"customer"` \| `"agent"` **in the frozen `salespilot/` build only**.
The rebuild emits `"customer"` \| `"business"`; see §1.2 and §5.8.

### 4.4 PATCH /api/cases/{id}

Body validated by a request model: `{ "status": "TAKEN_OVER" }`.

| Condition | Status |
| --- | --- |
| Success | 200, returns the updated case |
| Missing or malformed body | **422** |
| Unrecognised status value | 400 |
| Unknown case id | 404 |

A transition also moves the flags on the linked opportunity. The two write
directions are symmetric, and a client can rely on the round trip:

| Transition | `human_takeover` | `human_intervention_required` |
| --- | --- | --- |
| → `TAKEN_OVER` | set **true** | unchanged |
| → `CLOSED` | set **false** | set **false** |
| → `OPEN` | unchanged | unchanged |

So a `PATCH` to `TAKEN_OVER` is sufficient on its own to make
`POST /api/admin/opportunities/{id}/rep-reply` return 200 instead of 409 — no
escalation is needed in between, and the console does not have to check the flag
separately before enabling its reply box.

`CLOSED` resuming autonomous AI selling on the customer's next message is the
consequence any UI offering "resolve" must state. `OPEN` deliberately claims
nothing: an open case means the assistant is still handling the conversation and
nobody has taken it.

`human_intervention_required` survives a takeover because it records that a person
was *needed*, which taking the case over does not change.

### 4.5 Error format

FastAPI default: `{"detail": "<message>"}`. Validation failures return 422 with
FastAPI's structured error array. There is no application-specific error
envelope; frontends must not depend on one and should treat any non-2xx as a
transport-level failure with a generic user-facing message.

---

## 5. The live contract

> **This is the integration target.** Every item below is implemented in `backend/` and
> was verified against a running server on 2026-09-22. `POST /api/admin/seed` populates
> four conversations to check against, and `/docs` serves the generated schema.

Each item has a corresponding entry in
`docs/backend-contract.md` carrying the test and acceptance criteria.

### 5.1 Tier separation by namespace

Split the surfaces so the customer response has no shape for sensitive data.

**Customer surface**

| Method | Path | Returns |
| --- | --- | --- |
| POST | `/api/messages` | `reply`, `facts`, `quick_replies`, `client_message_id`, `human_takeover` — nothing from the "no" column of §2 |
| GET | `/api/conversations/{id}` | Safe transcript: `id`, `ts`, `role`, `author`, `rep_name`, `generation`, `text`, `client_message_id` |
| DELETE | `/api/conversations/{id}` | Reset |

**Admin surface** — `/api/admin/*`: opportunities with full intelligence, cases,
dashboard, analytics, and agent runs per §5.3.

Existing paths may remain as admin aliases during migration. The customer app
must stop calling `GET /api/opportunities/{id}`.

### 5.2 The `author` field

Add `author` to every message per §1.2. Additive and backward compatible: absent
means `"ai"` for agent-side messages.

### 5.3 Agent run telemetry

The admin console must be able to see what the agent actually did: which
operations ran, which tools were called, how many model calls, how many tokens,
how long, what it cost, and the input and output content with lengths.

```
GET /api/admin/agent-runs?opportunity_id=<required>&client_message_id=&limit=
GET /api/admin/agent-runs/{run_id}
GET /api/admin/opportunities/{id}/cost
```

**`opportunity_id` is required** on the list endpoint; omitting it returns `422`, not
an unfiltered list. There is deliberately no "all runs" query: the useful question is
always about one conversation, and an unbounded list grows with every message ever
sent.

The list returns a counted envelope, `{ "count": n, "items": [...] }`, whose items are
whole run objects of the shape below rather than summaries.

```json
{
  "run_id": "ar-91c4",
  "opportunity_id": "C-1024",
  "client_message_id": "c-8f2a1b40",
  "trigger": "customer_message",
  "customer_message_count": 3,
  "started_at": "ISO-8601",
  "finished_at": "ISO-8601",
  "duration_ms": 1240,
  "status": "ok",
  "steps": [
    { "index":  0, "name": "extraction",          "kind": "llm",       "duration_ms": 820, "status": "ok", "detail": null },
    { "index":  1, "name": "takeover",            "kind": "rule",      "duration_ms": 0,   "status": "ok", "detail": "No human takeover — the pipeline proceeds normally" },
    { "index":  2, "name": "state_transition",    "kind": "rule",      "duration_ms": 0,   "status": "ok", "detail": "Potential Interest -> Evaluation & Hesitation" },
    { "index":  3, "name": "profile_update",      "kind": "rule",      "duration_ms": 0,   "status": "ok", "detail": null },
    { "index":  4, "name": "qualification",       "kind": "rule",      "duration_ms": 0,   "status": "ok", "detail": null },
    { "index":  5, "name": "scoring",             "kind": "rule",      "duration_ms": 0,   "status": "ok", "detail": "fit 73 / behaviour 82 -> HIGH" },
    { "index":  6, "name": "next_best_action",    "kind": "rule",      "duration_ms": 0,   "status": "ok", "detail": null },
    { "index":  7, "name": "knowledge_retrieval", "kind": "retrieval", "duration_ms": 12,  "status": "ok", "detail": "3 facts, confidence 0.95" },
    { "index":  8, "name": "hitl",                "kind": "rule",      "duration_ms": 0,   "status": "ok", "detail": null },
    { "index":  9, "name": "quick_replies",       "kind": "rule",      "duration_ms": 0,   "status": "ok", "detail": null },
    { "index": 10, "name": "response_generation", "kind": "llm",       "duration_ms": 400, "status": "ok", "detail": null }
  ],
  "llm_calls": [
    {
      "index": 0,
      "purpose": "extraction",
      "model": "gpt-4o-mini",
      "duration_ms": 820,
      "prompt_tokens": 412,
      "completion_tokens": 88,
      "total_tokens": 500,
      "cost": { "amount": 0.00021, "currency": "USD", "pricing_known": true },
      "input":  { "chars": 2180, "content": "…" },
      "output": { "chars": 142,  "content": "…" }
    }
  ],
  "tool_calls": [
    { "index": 0, "name": "lookup_product_fact", "arguments": { "product": "plus", "field": "premium" }, "result_chars": 118 }
  ],
  "violations": [],
  "totals": {
    "agent_step_count": 11,
    "llm_call_count": 2,
    "tool_call_count": 1,
    "total_tokens": 500,
    "cost": { "amount": 0.00021, "currency": "USD", "pricing_known": true }
  }
}
```

Requirements:

1. `status` is `"ok"` \| `"degraded"` \| `"error"`. `degraded` covers a real case
   already in the code: the LLM extractor failing and falling back to rules. That
   is invisible today except as `extraction_source`.
2. **Cost is computed server-side.** The model name and any price table live in
   the backend; a frontend holding pricing would be business logic in the wrong
   layer.
3. `kind` is `"llm"` \| `"rule"` \| `"retrieval"` \| `"tool"`. `"tool"` is
   reserved for model-selected calls and is unused today (§1.1 rule 2).
4. `input.content` and `output.content` carry prompts and raw model output. They may
   contain the customer's own words, so they are gated by a backend flag —
   `SALESPILOT_TELEMETRY_CONTENT`, which is **on by default**. That is a deliberate
   reversal of this document's original "off by default": the point of the admin
   surface is to show what the agent actually did, and a hidden prompt cannot be
   reviewed. Turn it off for anything resembling production. `chars` is always
   present; `content` may be `null`, and a frontend must render length-only when it
   is. Never exposed on the customer tier under any setting.
5. Runs are **persisted per message** so the Inbox can show history, not only the
   most recent exchange.
6. Cost and token totals are queryable per conversation:
   `GET /api/admin/opportunities/{id}/cost` returns
   `{ "opportunity_id", "run_count", "total_tokens", "cost" }`.
7. **`cost` carries `pricing_known`, and it is not decoration.** Zero and unknown are
   different claims: a model absent from the backend's price table returns
   `{"amount": 0.0, "pricing_known": false}`, which means "no idea", not "free". A
   frontend must render the unknown case as unknown rather than as `$0.00`, or it
   invites somebody to budget against a number that is not one.
8. `steps[].detail` carries the reason a step is `degraded` or `error`, and useful
   context when it is `ok` — the state transition, the score decomposition, the
   retrieval confidence. A degraded step with no detail rendered reduces to the bare
   word "degraded", which is the report this whole surface exists to replace.
9. `violations` lists values the model returned that the domain rejected, each with
   `field`, `value`, `allowed` and `message`. Normally empty. A non-empty array means
   the model and the domain have drifted — the defect class that motivated the
   rebuild — so it is worth surfacing rather than collapsing into the status.

### 5.4 Human representative reply

```
POST /api/admin/opportunities/{id}/rep-reply
{ "text": "...", "rep_name": "Alex", "client_message_id": "r-1a2b" }
```

Appends `role: "business", author: "human", generation: "human"` **without** running
detection, scoring, state transition or HITL. A human turn is not a sales signal to be
analysed, and running the pipeline over it would move the score on the strength of the
representative's own words.

Rejected with `409` when the opportunity is not under human takeover. One `PATCH` of
the linked case to `TAKEN_OVER` is sufficient to lift that — see §4.4 for the flag
semantics, which are symmetric in both directions.

The original design treated takeover as a **channel switch**, which is why no write
path for a human message existed; that model was replaced rather than worked around.

### 5.5 Quick replies

Unchanged from `docs/backend-contract.md` Part B item 2. At most three, labels at
most 24 characters, empty while `human_takeover` is true.

### 5.6 Incremental fetch

```
GET /api/conversations/{id}?since=<message id | ISO-8601 timestamp>
GET /api/admin/opportunities/{id}?since=<same>&history_limit=<n>
```

**The cursor is a message `id` or an ISO-8601 timestamp — not an index.** Anything else
returns `400` with a message naming both accepted forms. Worth stating plainly because
an index is the natural guess and `?since=0` looks like it should mean "from the
start"; it does not, it is a `400`. Take the cursor from the `id` or `ts` of the last
message already held.

Returns the messages strictly *after* the cursor, so polling with the last known id
yields an empty list until something new arrives. An unknown conversation is `404`.

`history_limit` on the admin profile bounds `score_history` and `state_history`, which
otherwise grow with the conversation and make a poll cost more with every turn.

### 5.7 `generation` — how an agent-side message was produced

Raised by the backend track. `author` (§1.2) answers *who*; it does not answer
*how*, and the difference is now user-visible: the backend runs a full offline mode
in which replies are produced from deterministic templates with **no model call at
all**. A reader must never be misled about whether they are looking at a model, a
template, or a person.

Following §1's rule, this is a third field rather than a fourth `author` value.
`role` = which side, `author` = who, `generation` = how.

| Field | Values | Applies to |
| --- | --- | --- |
| `generation` | `"llm"` \| `"template"` \| `"human"` \| `null` | Agent-side messages. `null` for customer messages. |

The combinations the backend will emit, and nothing else:

| `role` | `author` | `generation` | Meaning |
| --- | --- | --- | --- |
| `customer` | `null` | `null` | The customer's own message |
| `business` | `ai` | `llm` | AI reply, a model produced the wording |
| `business` | `ai` | `template` | AI reply in **offline mode** — no model was called |
| `business` | `human` | `human` | A human representative wrote it |
| `business` | `system` | `template` | Deterministic system notice, e.g. a handover message |

These five are enforced at construction, not merely documented: `backend/domain/message.py`
rejects any other combination, so an impossible message — a human whose words were
"generated by a template", or a business reply that will not say whether a model
produced it — cannot be stored or served.

Why `"ai" + "template"` rather than a distinct author: the reply is still the
assistant speaking with the assistant's identity, so the compliance requirement to
label the assistant as AI (`.kiro/steering/product.md`) still applies. What changed
is only the means of production, which is what `generation` reports.

Additive and backward compatible: absent means `"llm"` for agent-side messages, so
an adapter that ignores the field behaves exactly as today.

**Requested of the frontend.** The customer app should make offline replies visually
distinguishable — a badge or equivalent on `generation: "template"` is enough; no
specific treatment is mandated. The admin console should show all three values,
since telling a model reply from a template reply from a colleague's reply is the
point of the transcript view.

**Acceptance.** Every business-side message in `opportunity.messages` and in the
customer-tier transcript carries a non-null `generation`. Running with no model
configured produces `generation: "template"` throughout and a `degraded` agent run
(§5.3). A rep reply produces `"human"`.

### 5.8 Rename `role: "agent"` to `role: "business"`

Specified in §1.2, including the reasoning and the rejected alternatives.

The rebuild emits `"customer"` and `"business"` only. No transitional alias: a
closed set with a deprecated third member is no longer closed, and the migration
cost is near zero today (§1.2 *Migration*).

**Requested of the frontend.** One line in each adapter, plus the `role: 'agent'`
occurrences in `frontend/admin/js/gateway/mock.js` fixtures. No view code is
affected, because neither app branches on the wire value.

**Acceptance.**

1. No response from the rebuild contains `"role": "agent"`.
2. Every message carries `role` equal to `"customer"` or `"business"`.
3. A human representative reply is `role: "business"`, `author: "human"`,
   `generation: "human"` — representable without contradiction, which is the point
   of the rename.

### 5.9 Two-axis score and qualification — and how `priority` is derived

Added because §4.3's single threshold is still the only derivation this document
described, and it is wrong for the live API. Gap register item 13.

**Admin tier only.** `score` on an opportunity, and on each message result:

```json
"score": {
  "need_identified": 40, "product_potential": 30, "expansion": 3, "fit_total": 73,
  "purchase_intent": 33, "purchase_readiness": 28, "engagement": 21,
  "engagement_depth": 9, "engagement_urgency": 6, "engagement_recency": 6,
  "behaviour_raw": 82, "behaviour_total": 82,
  "total": 78,
  "priority": "HIGH"
}
```

Also on the opportunity: `qualification` (`"qualified"` \| `"held"` \|
`"disqualified"`) and `qualification_reason`.

Four rules a client has to respect:

1. **`total` is display-only.** It is a headline for a human reader. **Ranking uses
   `priority`**, which comes from a fit × behaviour matrix, not from a threshold on
   `total`. The two disagree: see §4.3 for the two seeded conversations where the old
   rule demotes a served `HIGH` to `MEDIUM`.
2. **`priority` still serialises as exactly `HIGH` \| `MEDIUM` \| `LOW`.** Only the
   derivation changed, so badge and count logic is unaffected.
3. **Never recompute any of it.** The frontend holds no business logic
   (`.kiro/steering/frontend-conventions.md`). Every field above is served; a client
   that derives one has two answers to the same question.
4. **`behaviour_raw` versus `behaviour_total`.** The behaviour axis decays
   multiplicatively with silence, to a floor. When they differ, the gap *is* the
   decay, and showing both is what makes a low score reviewable — "raw 82, decayed
   after forty days" is inspectable where "behaviour 29" is not. Fit never decays:
   silence does not make a corporate account worth less, it makes it colder.

**Qualification is not a synonym for low priority.** `held` means the conversation is
not a sales opportunity — advertising, most often — so the assistant stops advancing
the sale and the opportunity is **absent from the sales queue** while still being
scored. Only a human sets `disqualified`; the machine may reach `held` and no further,
so a false hold costs one click. `qualification_reason` carries why, and the same
reason appears on the agent run's `qualification` step.

---

## 6. Frontend degradation matrix

**Historical, for every row below.** These described how each frontend coped while §5
was outstanding. Nothing in §5 is outstanding any more, so the fallbacks should be
retired rather than kept warm — an adapter still mapping `role: "agent"`, or still
labelling telemetry "not reported by backend", is now wrong rather than degraded.

What survives is the *other* degradation axis, which is permanent and is about runtime
rather than delivery: with no model configured every business message reports
`generation: "template"`, each run reports `status: "degraded"` with the reason on the
step that degraded, and `/health` returns `degraded: true` with
`degradation_reason`. A frontend must keep handling that, because it is the default
mode, not a fault.

| Proposal | Customer app *(while outstanding)* | Admin console *(while outstanding)* |
| --- | --- | --- |
| 5.1 tiers | Calls today's endpoints, discards sensitive fields at the adapter boundary | No change |
| 5.2 `author` | Treats agent messages as `"ai"` | Cannot distinguish AI from human in a transcript |
| 5.7 `generation` | Treats business messages as `"llm"`; no offline badge | Cannot tell a model reply from a template reply |
| 5.8 `role` rename | Adapter maps `"agent"` today, `"business"` after the switch | Same, plus mock fixtures updated |
| 5.3 telemetry | Not applicable — never receives it | Debug panel shows client-observed timing and status only; token, cost, prompts and steps read "not reported by backend" |
| 5.4 rep reply | No change | Composer visible but disabled, with the reason stated |
| 5.5 quick replies | No chips | No change |
| 5.6 since cursor | Polls the full transcript and diffs locally | No change |

---

## 7. Change log for v1

| Date | Track | Change |
| --- | --- | --- |
| 2026-09-22 | frontend | Created. Supersedes `backend-contract.md` Part A. Recorded §1 naming discipline (`turns` family, `role` vs `author`), §2 server-side visibility tiers, §3 two-plane topology and telemetry correlation, §4 current contract after the backend refactor, §5 proposals including agent run telemetry. |
| 2026-09-22 | backend | Added §5.7 `generation`, a third axis recording how a business-side message was produced (`llm` / `template` / `human`). Motivated by the offline mode being user-visible: a template reply involves no model call and must not be presented as one. Added the matching row to §6. Accepted §1 and §2 as written; they will be implemented by the `backend/` rebuild rather than retrofitted into `salespilot/` — see `docs/backend-plan.md` §2. |
| 2026-09-22 | backend | **Renamed `role: "agent"` to `role: "business"`** (§1.2, §5.8). The old value implied "AI agent", so a human representative's message under it read as a contradiction — the same one-field-two-meanings defect §1 exists to prevent. Done now because the cost is near zero: neither real adapter is written, no view code branches on the wire value, and the only shipped occurrences are admin mock fixtures. No transitional alias. |
| 2026-09-22 | backend | `salespilot/` is frozen and will be discarded once the rebuild lands. §4 therefore describes the frozen build; the authoritative target for both adapters is §5. |
| 2026-09-22 | backend | Raised two gaps in `backend-contract.md` rather than specifying them here yet, since both need a shape agreed with the frontend: **item 12**, an incremental cursor for the admin conversation read — §5.6 covers only the customer surface, while the admin side polls the full profile and is the one that grows quadratically over a session; **item 13**, two-axis scoring with a qualification gate, adding admin-tier `fit`, `behaviour` and `qualification` fields. `priority` keeps exactly its three existing values in both cases; only its derivation changes, so badge and count logic is unaffected. |
| 2026-09-22 | backend | §4.4 now specifies **both** write directions of a case transition, not only `CLOSED`. `→ TAKEN_OVER` sets `human_takeover`, so a single `PATCH` is enough to make `rep-reply` return 200; `→ OPEN` claims nothing. Previously only the close direction was documented, and only the close direction was implemented, so the console could take a case over successfully and still have its reply refused. `docs/backend-contract.md` item 14. |
| 2026-09-22 | backend | The API now sends CORS headers for configured loopback development origins, which unblocks both frontends running in a browser rather than only from Node. No wire shape changes; `docs/backend-contract.md` item 15. Not specified here because it is transport configuration rather than contract — the only thing a client needs to know is that its origin must appear in `SALESPILOT_CORS_ORIGINS`. |
| 2026-09-22 | backend | §5.3 cost figures are now real. `totals.llm_call_count`, `totals.total_tokens` and `totals.cost` were populated by nothing on the live path for three phases, so a run through a real provider reported zero calls and `cost: {"amount": 0.0, "pricing_known": true}` — measured and free, rather than unmeasured. A client that had treated a zero cost as authoritative would have been reading a fabrication. `pricing_known: false` remains the honest answer for a model absent from the price table. |
| 2026-09-22 | backend | **Full verification pass against a running server before freezing.** Every concrete claim in this file was checked against `py -3 -m backend --serve --seed` rather than against memory. Six corrections were needed and are listed in the rows below; the enumerations in §4.3 (14 intents, 5 products, 6 states, 11 signals, 3 priorities, 3 case statuses), the `quick_replies` bounds, the customer-tier payload shape and the error-status mapping all checked out unchanged. |
| 2026-09-22 | backend | **The header's `PROPOSED` instruction was withdrawn, and §4 / §5 retitled.** The two halves had swapped meaning: §4 "Current contract" describes the frozen `salespilot/` build, while §5 "Proposed changes" is what actually ships. Since the header told frontends to treat every `PROPOSED` field as absent and degrade, following this document literally meant discarding the entire live contract. §5 is now "The live contract" and §4 is marked historical. |
| 2026-09-22 | backend | **§4.3's priority rule is wrong for the live API, and now says so.** `HIGH (score ≥ 80) / MEDIUM (≥ 50) / LOW (< 50)` was the frozen build's single threshold. Measured on the seeded queue it disagrees with the served `priority` on two of four conversations, in the damaging direction: Sarah (fit 73, behaviour 82, total 78) and ABC Pte Ltd (fit 80, behaviour 74, total 77) are served `HIGH` and the old rule computes `MEDIUM`, demoting the two genuine high-intent customers. Added **§5.9** specifying the two-axis score, the qualification gate, and that `total` is display-only while ranking comes from `priority`. |
| 2026-09-22 | backend | **§5.6 now states what the `since` cursor is:** a message `id` or an ISO-8601 timestamp, never an index. An index is the natural guess and returns `400`; `?since=0` in particular looks like "from the start" and is not. Also documented `history_limit` on the admin profile. |
| 2026-09-22 | backend | **§5.3 corrections.** `opportunity_id` is **required** on `GET /api/admin/agent-runs` (422 without it), where the parameter list read as optional; the list returns a `{count, items}` envelope of whole runs. `cost` carries **`pricing_known`**, which was missing from both examples and is the field separating zero from unmeasured. `steps[].detail` and the run's `violations` array were undocumented — `detail` is where a degradation reason lives, so a console rendering only `status` reduces every one of them to the word "degraded". The step example showed 5 steps; there are 11, and the names are what a console displays. Named the per-conversation cost endpoint, `GET /api/admin/opportunities/{id}/cost`. |
| 2026-09-22 | backend | **§5.3 requirement 4 reversed: telemetry content is `on` by default, not off.** The document said off; `SALESPILOT_TELEMETRY_CONTENT` defaults to on, deliberately — the point of the admin surface is to show what the agent actually did, and a hidden prompt cannot be reviewed. Recorded as a decision rather than quietly corrected, since a reader had been told prompts were withheld when they are returned. Never exposed on the customer tier under any setting. |
| 2026-09-22 | backend | **§5.7's combination table still said `role: "agent"`**, contradicting §5.8 and the code four sections later in the same document. Corrected to `business`, and noted that the five combinations are enforced at construction in `backend/domain/message.py` rather than merely documented. §5.4's "blocked by a product decision" preamble was removed — it shipped. §6 is marked historical: an adapter still mapping `"agent"` or labelling telemetry "not reported by backend" is now wrong rather than degraded, while the *runtime* degradation it also describes (offline mode) is permanent and must still be handled. |
| 2026-09-22 | backend | **§1.1's "Today" column misdescribed the system in four places** and has been rewritten as "Where it is served". `agent_step_count` said a fixed 12-step sequence (it is 11); `tool_call_count` said **0, there is no tool-calling loop** and rule 2 said `tool_calls` stays an empty array — there is a loop and the array is populated, which makes the retrieval-is-not-a-tool rule matter *more*, not less. Worst of the four: rule 3 still named `min(12, 3 + 2 * turns)` as the engagement dimension and called it load-bearing. That formula is gone, replaced by the two-axis model in §5.9 — and it is the formula whose replay-inflation defect started the rebuild, so a frozen contract presenting it as current would have been quoting the bug. §2 additionally now lists `message` and `human_takeover`, both returned on the customer tier and both previously unlisted, and clarifies that customer-visible `facts` is the permitted-this-turn list rather than `retrieval.facts`. |
| 2026-09-22 | backend | **`Status: frozen`. This is the last entry.** v1 is closed to both tracks: §5 is the contract, §4 is historical, and the corrections above were all made before the freeze rather than after it. From here a contract change means `interface-v2.md`, and so does a *correction* — anything found wrong in this file is recorded in `docs/backend-contract.md` and specified in v2, never patched in place, because a quietly corrected contract gives neither track the one thing freezing is for. Gap register items 1–15 are all shipped and served; `backend/tests` 421 passed, the frozen `tests` 80 passed. What remains before the demo is on the frontend side of the boundary: running both apps against `backend/` on port 8000 with their real adapters, which the backend no longer prevents. |
