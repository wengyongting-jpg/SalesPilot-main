# Backend API contract

Audience: the backend team, and any frontend developer integrating against the
SalesPilot REST API.

This document has two halves:

- **Part A — Current API.** What exists today, verified against
  `salespilot/api/app.py` and `salespilot/api/schemas.py`. Frontends integrate
  against this and must work with it as-is.
- **Part B — Required changes.** Gaps the frontends hit, each with the reason, the
  proposed shape, a test, and acceptance criteria. Frontends must **degrade
  gracefully** while these are outstanding, never block on them.

Terminology: this document covers only the **backend REST API** consumed by the
frontends. The separate OpenAI-compatible *provider API* the backend uses to
reach an LLM is internal and out of scope here.

---

## Part A — Current API

Base URL in development: `http://127.0.0.1:8000`. Start with:

```powershell
py -3 run.py --serve --seed
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
  "text": "How much does CareSure Plus cost?"
}
```

`customer_name` is required. `customer_id` defaults to `""` (the backend then
generates one). `text` must be at least 1 character.

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
      { "ts": "ISO-8601", "role": "customer", "text": "..." },
      { "ts": "ISO-8601", "role": "agent", "text": "..." }
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

### 1. Message idempotency — P0, correctness bug

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
idempotency support.

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

---

## Change log for this contract

Keep this table current when Part B items land, so frontend adapters know what to
enable.

| Date | Item | Status |
| --- | --- | --- |
| — | 1. Message idempotency | Not started |
| — | 2. Quick replies | Not started |
| — | 3. Incremental fetch | Not started |
| — | 4. Rep reply | Not started |
| — | 5. Message id / status | Not started |
