# Backend handoff — parallel frontend/backend development

**To:** the agent or developer owning the Python backend
**From:** the frontend track
**Status:** customer chat partly built (mock transport); admin console next

> **Updated 2026-09-22.** Two things changed since this document was written.
>
> 1. **The authoritative contract moved.** Shapes are now specified in
>    **[`docs/api/interface-v1.md`](api/interface-v1.md)**, a file both tracks
>    edit. It wins over `backend-contract.md` and over this file wherever they
>    disagree about a payload. `backend-contract.md` is now the gap register:
>    one entry per requested change, with a test and acceptance criteria.
> 2. **Thank you for item 1.** Message idempotency shipped with tests, and the
>    two always-true `hasattr` guards you removed were real dead code we had
>    flagged as a smell. The frontend degradation for it has been retired.
>
> Four new items are registered: **6** visibility tiers, **7** the `author`
> field, **8** agent run telemetry, **9** renaming the `turns` counter. Item
> **4** (rep reply) rose to **P0**. Start with §3.1 below.

## 0. Read this first: one field, one meaning

Two defects of the same class have now been found, and the second one you
identified yourself:

- **`opportunity.turns`** is a count of *customer messages*. It is read
  everywhere as "agent turns". It is not.
- **`role`** answers *which side of the conversation*, not *who wrote it*. Your
  own comment in `models.py` says the authorship axis "is not encoded here".

Both are one field carrying two meanings. The cost is not an exception — it is a
plausible-looking wrong number, or an unrepresentable concept, discovered late.
`docs/api/interface-v1.md` §1 fixes the vocabulary: five distinct counters with
distinct names, and `role` plus `author` as orthogonal axes.

One consequence worth stating plainly, because it is a trap: **RAG retrieval is
not a tool call.** It is a fixed pipeline step, not something the model chose.
`tool_calls` must stay an empty array until a genuine tool-calling loop exists.
Filling it to make a dashboard look richer would manufacture the third instance
of this same defect.

We are working in parallel. This document is the coordination contract between the
two tracks: who owns what, what the frontend needs from you and in what order,
and which existing behaviour must not change underneath us.

The detailed specification of every change requested is in
**[`docs/backend-contract.md`](backend-contract.md)**. That file is the single
source of truth for shapes, tests and acceptance criteria. This document is the
*why, who and when* around it. Read this first, then Part B of that file.

---

## 1. Division of ownership

| Area | Owner | Rule |
| --- | --- | --- |
| `backend/**` | **Backend** | The rebuild, created 2026-09-22 by copying `salespilot/`. Same read-only rule for the frontend track. This is the codebase that implements `docs/api/interface-v1.md` §5; see `docs/backend-plan.md` §2. |
| `salespilot/**` (except `static/`) | **Backend** | Frontend treats it as read-only. We read it to understand the contract; we never edit it. Its HTTP surface is now **frozen** at what it serves today — it receives correctness fixes only and stays runnable as the fallback demo. |
| `tests/**`, `run.py`, `requirements.txt` | **Backend** | Same. |
| `salespilot/data/**` | **Backend** | The knowledge base moved here from the repository root on 2026-09-22, since it is backend-owned data. It is now covered by the `salespilot/**` rule above. |
| `salespilot/static/**` (legacy console) | **Frozen** | Neither track changes it. See §5. |
| `frontend/customer/**`, `frontend/admin/**` | **Frontend** | Please treat as read-only from your side. |
| `docs/backend-contract.md` | **Shared** | You update the status table; we add newly discovered gaps. |
| `docs/api/interface-v1.md` | **Shared** | Per its own header: while `Status: draft`, either track edits directly and records the change in §7. |
| `docs/backend-plan.md` | **Backend** | The rebuild plan. **Read-only for the frontend track** — raise concerns rather than editing. |
| `docs/backend-changelog.md` | **Gated** | Owner authorisation required before any entry. Backend counterpart of the frontend changelog. |
| `docs/frontend-changelog.md` | **Gated** | Owner authorisation required before any entry. Do not write to it. |
| `.kiro/specs/customer-chat-ui/**`, `.kiro/specs/admin-console-ui/**` | **Frontend** | Reference freely. |
| `.kiro/steering/**` | **Shared** | Propose changes rather than rewriting. |

If you believe a frontend file must change to accommodate a backend decision, say
so rather than editing it. The reverse rule binds us equally.

## 2. What we are building

Two new independent frontends under `frontend/`, both vanilla HTML/CSS/JS with no
build step:

- **`frontend/customer/`** — a WhatsApp-style customer chat. Shows *only* the
  conversation. It deliberately discards `score`, `priority`, `signals`, `state`,
  `next_best_action` and `case` at the adapter boundary so internal sales
  intelligence cannot leak to a customer.
- **`frontend/admin/`** — a trimmed staff console: opportunity queue, case
  takeover, customer detail. This one displays the sales intelligence in full.

Both consume the existing `/api/*` REST surface. Neither touches the provider
(LLM) layer.

Terminology we are keeping strict, because it caused confusion once already:

- **Provider API** — the OpenAI-compatible endpoint *you* call to reach a model
  (`salespilot/providers/llm.py`). Entirely yours. The frontend never sees it.
- **Backend REST API** — `/api/*` in `salespilot/api/app.py`. The only shared
  surface. When this document says "the API", it means this.

## 3. What we need from you, in priority order

Full specs, request/response shapes, `curl` tests and acceptance criteria are in
`backend-contract.md` Part B. Payload shapes are in
`docs/api/interface-v1.md`. Summary and rationale here.

### 3.1 Current priority order

| | Item | Why now |
| --- | --- | --- |
| 1 | **6. Visibility tiers** (P0) | Blocks item 8 safely. Prompts and cost cannot ship to a customer's browser. |
| 2 | **4. Rep reply** (P0, raised) | Blocks the admin console's primary route. Needs a product decision first — see below. |
| 3 | **7. `author` field** (P1) | Small, additive, and a prerequisite for showing who spoke in the admin transcript. |
| 4 | **8. Agent run telemetry** (P1) | The admin console's reason to exist. Do it after item 6. |
| 5 | **2. Quick replies** (P1) | Customer-visible polish. |
| 6 | **9. Rename `turns`** (P2) | Cheap, prevents recurring confusion. |
| 7 | **3. Incremental fetch** (P2) | Efficiency only. |
| 8 | **5. Message id / status** (P3) | Optional; our ticks are already honest without it. |

### 3.2 The product decision blocking item 4

You wrote that a human-reply write path is missing because "the original design
treats takeover as a channel switch". That reading is consistent with the code,
and it is the crux.

The repository owner has specified that the admin console's **primary route** is
staff input directed at a consumer. That requires takeover to mean *a human
continues the conversation in this system*, not *the conversation leaves this
system*. So the channel-switch model needs to be replaced, not worked around.

Concretely, this is what we need to exist: a human message appended to the
transcript as `role: "business"`, `author: "human"`, **without** running detection,
scoring, state transition or HITL evaluation — because the human is talking, not
the agent. Rejected when the opportunity is not under takeover, so the endpoint
cannot be used to bypass the pipeline.

If you see a better model for representing a human turn, propose it in
`interface-v1.md` §5.4 rather than here; that file is shared and we will pick it
up.

### 3.3 Why visibility tiers come before telemetry

Item 8 adds prompt text, token counts and spend to the system. Item 6 ensures
there is no customer-facing shape those can travel through. Shipping 8 before 6
would put model prompts and cost data in a customer's browser, hidden only by our
client-side discipline. Please land 6 first.

### Item 1: message idempotency — **SHIPPED 2026-09-22**

Kept for context; no action needed.

`POST /api/messages` is not idempotent. Every call appends the message, increments
`opportunity.turns`, and re-runs the state machine and scoring.

This is a genuine correctness bug, not a frontend convenience. Because the
engagement dimension is `min(12, 3 + 2 * turns)` in
`salespilot/engine/scoring.py`, a single network-timeout retry inflates the
opportunity value score for an event that never happened. A customer could be
promoted toward HIGH priority by a flaky connection.

We are already generating and sending a `client_message_id` on every send, and
reusing it on retry. We need the server to deduplicate on it. Until then our retry
control carries an accessible warning that retrying may duplicate — a visible
wart we would like to remove.

**This is the one item we would ask you to do first even though it is not the one
that unblocks the most UI.**

### P1 — Item 2: `quick_replies` in the response

We need up to three short suggested replies in the `POST /api/messages` response,
derived from your deterministic decision layer — not free-text from the LLM.

We are explicitly *not* deriving these client-side. Inferring suggestions from
state and next-best-action would put business logic in the frontend, which both
specs forbid. So this feature simply does not exist until you ship it, and the UI
renders no chips. That is an acceptable degradation, just a less impressive demo.

Constraint worth noting: chips must be empty while `human_takeover` is true. Once a
human owns the case, the AI should not be steering the customer.

### P2 — Item 3: incremental message fetch

`GET /api/opportunities/{id}/messages?since=` so polling does not re-transfer the
entire transcript. We currently poll the full profile and diff locally. Correct but
wasteful. Low urgency.

### P2 — Item 4: human representative reply

There is currently **no way for a human to post a message into a conversation**.
`POST /api/messages` is customer-input-only and always runs the full pipeline.

The consequence is architectural, not cosmetic: after a case is taken over, the
representative cannot actually reply. So "human handoff" today means *the AI stops
selling*, not *a human starts talking*. Our admin console will ship a disabled
reply box explaining this, and the customer app will poll but only ever observe AI
replies.

This is the single change that makes live updates meaningful. If you want the demo
to show a real human joining the conversation, this is the item to build.

### P3 — Item 5: message ids and delivery status

Deliberately low priority. We map delivery ticks to real client-observable events —
clock on request-in-flight, single tick on HTTP 2xx, double tick when the reply
renders — so we need nothing from you for honest tick behaviour. Only build this if
you want true server-side receipts later.

## 4. Contracts you must not break

These are things the frontends depend on. Changing any of them silently will break
us with no compile-time warning, since we have no build step and no type checking.

### Serialised string values

| Contract | Values | Depended on by |
| --- | --- | --- |
| Case status | `"Open"`, `"Taken Over"`, `"Closed"` — exact, title case | Admin console control logic |
| Opportunity state | the six exact strings, incl. `"Evaluation & Hesitation"` and `"Closed / Active Customer"` | Admin queue and detail |
| Priority | `"HIGH"`, `"MEDIUM"`, `"LOW"` uppercase | Badge and count logic |
| Product | `"essential"`, `"family"`, `"plus"`, `"corporate"`, `"unknown"` lowercase | Label maps, product cards |
| Signals | the 11 exact values, incl. the `"Expansion: Family"` colon-space form | Signal labels |

There is already a test guarding the first of these — `test_case_status_contract`
in `tests/test_api.py`, labelled `U1`, whose docstring says it exists because the
frontend normalises those tokens. That is exactly the right instinct. **Please
extend that pattern to the other four rows.** The `U` series currently uses
`U1`, `U3`, `U4`; `U2` appears unused, so `U5` onward is free.

### Response field stability

- `POST /api/messages` must keep returning `retrieval.facts` as a structured
  array. Our product cards are built from it, verbatim. If facts ever collapse into
  one prose string, cards break.
- `opportunity.messages` must stay append-only and in chronological order. We
  reconcile local `clientId`s by matching from the end; reordering would scramble
  tick state.
- `PATCH /api/cases/{id}` must keep returning the updated case object. We update
  from the response body rather than the requested value on purpose, so a
  transition that did not really happen cannot look like it did.
- Closing a case must keep clearing `human_takeover` on the opportunity. Our admin
  console tells the representative this will happen; if the behaviour changes, our
  warning becomes a lie.

### Additive changes are safe

Adding fields is always fine — we treat every Part B field as optional and detect
capabilities from what actually arrives rather than assuming. Renaming, retyping,
or removing fields is what hurts.

## 5. Things we found while reading your code

Reported for your judgement. None of these block us, and we have not touched any
of them.

1. **`PATCH /api/cases/{id}` reaches into a private attribute.** The in-memory
   fallback does `sales_agent.repo._cases = {c.id: c for c in cases}`, which
   assumes the repository's internal shape. Adding `update_case` to the in-memory
   repository so both branches use the public method would remove the coupling.
2. **`PATCH /api/cases/{id}` takes `body: dict = None`** rather than a Pydantic
   model, so the payload is unvalidated and the endpoint hand-rolls its status
   parsing. A small request model would make it consistent with
   `POST /api/messages`.
3. **The legacy console's chat-panel takeover button is cosmetic.**
   `executeTakeover()` in `salespilot/static/app.js` only toggles CSS classes and
   never calls `PATCH /api/cases/{id}`, even though the endpoint exists. We are not
   fixing it because that file is frozen, but it means the legacy console's chat
   view misrepresents takeover state. Our admin console performs the real
   transition. Worth knowing if anyone demos the old UI.
4. **No authentication anywhere.** Any client can claim any `customer_id` and read
   or reset that conversation; anyone reaching the admin surface can take over or
   close any case. We have documented this as an accepted demo limitation in
   `.kiro/steering/product.md` and `backend-contract.md` rather than papering over
   it with a fake login. Flagging it so the decision stays deliberate, especially
   before anything is exposed beyond localhost.
5. **`py -3 run.py --demo` output mangles em dashes when piped** in PowerShell and
   exits non-zero in that case. Running it unpiped, or with
   `PYTHONIOENCODING=utf-8`, is clean. This looks environmental rather than a code
   defect, so we are not filing it as a bug — just noting it so a piped demo run
   does not alarm anyone.

## 6. How to report progress back

Please keep the status table at the bottom of `backend-contract.md` current:

```markdown
| Date | Item | Status |
| --- | --- | --- |
| 2026-09-22 | 1. Message idempotency | Shipped |
```

That table is what our adapters key their capability detection against
conceptually, and it is how we know when to remove a degradation. Marking an item
`Shipped` is our signal to enable the corresponding feature and delete the
workaround.

If you change a shape during implementation, please edit the relevant Part B
section rather than only telling us — the document is the contract, and a verbal
agreement will be lost.

## 7. Verification

Existing suite, which must stay green:

```powershell
py -3 -m pytest tests/ -v
# or, stdlib only
py -3 -m unittest discover -s tests -v
```

Test conventions already in the repository, worth matching:

- `tests/test_api.py` uses `fastapi.testclient.TestClient` with an in-memory
  `Repository`, and skips cleanly when FastAPI or httpx is absent.
- Contract-guarding tests carry a `U<n>` label in the docstring explaining what
  external consumer depends on the behaviour.
- Correctness fixes carry a `P0-<n>` label, referenced from both the test and the
  implementation comment. `P0-1` through `P0-4` are in use.

For each Part B item, the acceptance criteria in `backend-contract.md` are written
to be directly translatable into test assertions. Item 1's criteria in particular
are worth encoding as a regression test, since the failure mode is silent score
inflation rather than an exception.

Please do not add tests under `frontend/`; we will handle frontend verification,
which is manual and scripted by design — introducing a JS test runner would mean
introducing a build step.

## 8. What we will not ask you for

So you can plan without worrying about creeping scope from our side:

- No authentication or user accounts.
- No WebSocket or server-sent events. Polling during takeover is sufficient.
- No message editing, deletion, reactions, image upload, or voice notes.
- No localisation. The product is English-only.
- No changes to the decision engine: state machine, scoring weights, priority
  bands, next-best-action rules and HITL triggers are yours and we display them
  as-is. We will never recompute or re-band them client-side.
- No new analytics fields. The existing `/api/analytics` payload is more than our
  stretch scope needs.

## 9. Immediate next step

Our tracks do not block each other right now. Customer-chat tasks 1–3 and all
groundwork need no server at all, so we can run ahead while you pick up Item 1.

Suggested first exchange: you ship Item 1 with a regression test, update the status
table, and we verify against it with the `curl` sequence already written in
`backend-contract.md`. That gives us a working handshake on the smallest possible
change before the larger items.

If anything in `backend-contract.md` Part B looks wrong, over-specified, or more
expensive than it is worth, push back — it was written from the frontend's needs
and has not been costed against your implementation.
