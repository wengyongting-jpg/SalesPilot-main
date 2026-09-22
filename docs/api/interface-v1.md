# SalesPilot interface — v1

| | |
| --- | --- |
| **Version** | v1 |
| **Status** | `draft` — both tracks may edit directly |
| **Ownership** | **Shared.** Backend and frontend both edit this file. |
| **Supersedes** | `docs/backend-contract.md` Part A (the schema reference) |
| **Companions** | `docs/backend-contract.md` (gap register) · `docs/backend-handoff.md` (ownership and coordination) |

This is the **authoritative** request/response contract between the Python
backend and the two frontends. Where any other document disagrees with this one
about a shape, this one wins.

**Change rules.** While `Status` is `draft`, either track edits directly and
records the change in §7. Once `Status` becomes `frozen`, no edit is permitted:
create `interface-v2.md`, mark this file `frozen`, and point the new file at it.
Only one version is `current` at a time; this header says which.

**Sections marked `PROPOSED`** are not implemented yet. Frontends must treat every
`PROPOSED` field as absent and degrade rather than block. Sections marked
`CURRENT` are verified against the code.

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

| Name | Meaning | Today |
| --- | --- | --- |
| `customer_message_count` | How many messages the customer sent | **This is what `turns` actually is** |
| `agent_run_count` | How many times the pipeline executed end to end | 1:1 with the above today, but a different concept |
| `agent_step_count` | Steps within one run | Fixed 12-step sequence, not iterative |
| `llm_call_count` | Model invocations | 0 when rule-based, up to 2 (extraction + generation) |
| `tool_call_count` | Tool calls the **model chose** to make | **0 — there is no tool-calling loop** |

Rules:

1. **`turns` is deprecated as a name.** It stays in the payload for backward
   compatibility, but new fields must use `customer_message_count`, and
   documentation must never describe `turns` as "agent turns".
2. **Never label RAG retrieval a tool call.** Retrieval is a fixed pipeline step,
   not a model-selected tool. It is reported with `kind: "retrieval"`.
   `tool_calls` stays an empty array until a real tool-calling loop exists.
   Inventing a fake tool count to fill a dashboard would create exactly the
   defect this section exists to prevent.
3. The opportunity value score's engagement dimension is
   `min(12, 3 + 2 * turns)`, so it is coupled to a customer-message counter.
   Any redefinition of `turns` changes scores. Treat it as load-bearing.

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
| `retrieval.facts` | yes | Approved knowledge-base content; product cards need it |
| `retrieval.confidence` | **no** | Internal signal about retrieval quality |
| `quick_replies` | yes | Rendered as chips |
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

## 4. Current contract

`CURRENT` — verified against `salespilot/api/app.py`, `api/schemas.py` and
`models.py` as of the 2026-09-22 backend refactor (see `docs/backend-changelog.md`).

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

Priority: `HIGH` (score ≥ 80), `MEDIUM` (≥ 50), `LOW` (< 50).

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

Transitioning to `CLOSED` also clears `human_takeover` and
`human_intervention_required` on the linked opportunity, which resumes autonomous
AI selling on the customer's next message. Any UI that offers "resolve" must say
so.

### 4.5 Error format

FastAPI default: `{"detail": "<message>"}`. Validation failures return 422 with
FastAPI's structured error array. There is no application-specific error
envelope; frontends must not depend on one and should treat any non-2xx as a
transport-level failure with a generic user-facing message.

---

## 5. Proposed changes

`PROPOSED` — not implemented. Each item has a corresponding entry in
`docs/backend-contract.md` carrying the test and acceptance criteria.

### 5.1 Tier separation by namespace

Split the surfaces so the customer response has no shape for sensitive data.

**Customer surface**

| Method | Path | Returns |
| --- | --- | --- |
| POST | `/api/messages` | `reply`, `facts`, `quick_replies`, `client_message_id`, `human_takeover` — nothing from the "no" column of §2 |
| GET | `/api/conversations/{id}` | Safe transcript: `ts`, `role`, `author`, `text`, `client_message_id` |
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

`GET /api/admin/agent-runs?opportunity_id=&client_message_id=&limit=`
`GET /api/admin/agent-runs/{run_id}`

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
    { "index": 0, "name": "extraction",          "kind": "llm",       "duration_ms": 820, "status": "ok" },
    { "index": 1, "name": "state_transition",    "kind": "rule",      "duration_ms": 1,   "status": "ok" },
    { "index": 2, "name": "scoring",             "kind": "rule",      "duration_ms": 1,   "status": "ok" },
    { "index": 3, "name": "knowledge_retrieval", "kind": "retrieval", "duration_ms": 12,  "status": "ok" },
    { "index": 4, "name": "response_generation", "kind": "llm",       "duration_ms": 400, "status": "ok" }
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
      "cost": { "amount": 0.00021, "currency": "USD" },
      "input":  { "chars": 2180, "content": "…" },
      "output": { "chars": 142,  "content": "…" }
    }
  ],
  "tool_calls": [],
  "totals": {
    "agent_step_count": 5,
    "llm_call_count": 2,
    "tool_call_count": 0,
    "total_tokens": 500,
    "cost": { "amount": 0.00021, "currency": "USD" }
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
4. `input.content` and `output.content` carry prompts and raw model output.
   They may contain the customer's own words, so they are gated by a backend
   flag, **off by default**. `chars` is always present; `content` may be absent.
   A frontend must render length-only when content is withheld.
5. Runs are **persisted per message** so the Inbox can show history, not only the
   most recent exchange.
6. Cost and token totals must be queryable per conversation so the console can
   show a running total.

### 5.4 Human representative reply

Blocked by a product decision, not only a missing endpoint. The backend notes
that the original design treats takeover as a **channel switch**, which is why no
write path for a human message exists.

The admin Inbox route requires one, so the decision needs making. If a
representative replies inside the console:

```
POST /api/admin/opportunities/{id}/rep-reply
{ "text": "...", "rep_name": "Alex", "client_message_id": "r-1a2b" }
```

Appends `role: "business", author: "human", generation: "human"` **without** running detection, scoring,
state transition or HITL. Rejected with 409 when the opportunity is not under
human takeover.

**Priority raised from P2 to P0:** it now blocks the admin console's primary
route, not a secondary feature.

### 5.5 Quick replies

Unchanged from `docs/backend-contract.md` Part B item 2. At most three, labels at
most 24 characters, empty while `human_takeover` is true.

### 5.6 Incremental fetch

Unchanged from Part B item 3, retargeted at the customer surface:
`GET /api/conversations/{id}?since=`.

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
| `agent` | `ai` | `llm` | AI reply, a model produced the wording |
| `agent` | `ai` | `template` | AI reply in **offline mode** — no model was called |
| `agent` | `human` | `human` | A human representative wrote it |
| `agent` | `system` | `template` | Deterministic system notice, e.g. a handover message |

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

---

## 6. Frontend degradation matrix

How each frontend behaves while §5 is outstanding. No frontend work is blocked.

| Proposal | Customer app | Admin console |
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
