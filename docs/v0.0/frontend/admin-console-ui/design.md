# Design — Admin console UI

## Overview

Same architecture as the customer chat, so the two apps stay mentally
interchangeable: `views → store → gateway`, one direction, no framework, no build
step.

```
views/  ──reads──▶  store  ──calls──▶  gateway adapter  ──HTTP──▶  backend
   └────dispatch intent──┘◀────────normalised──────────┘
```

The inversion from the customer app is deliberate and total: the backend's typed
customer projection cannot express sales intelligence, while the admin adapter
keeps the full admin payload. The audience boundary is enforced server-side.

Three routes: **Inbox** (landing), **Cases**, **Harness**.

## Transport

Two adapters behind one interface, selected from config:

| Adapter | Use |
| --- | --- |
| `mock` | Scripted data, no network; useful for fixture-only UI work. |
| `salespilot` | Default. Live `/api/admin/*` integration. |

The backend visibility tiers are complete. Queue, conversation, case, human reply,
agent-run and health operations all use the live admin namespace.

Interface:

```js
createGateway(config) -> {
  listConversations()                  -> { items: ConversationSummary[] }
  getConversation(id)                  -> { opportunity, messages, linkedCase }
  listCases()                          -> { items: Case[] }
  updateCaseStatus(id, status)         -> Case
  listAgentRuns({ opportunityId, clientMessageId }) -> { items: AgentRun[] }
  sendRepReply({ id, text, repName, clientMessageId }) -> { message }
  seedDemoData()                       -> { seeded: boolean }
  health()                             -> boolean
  readonly name
  readonly capabilities                -> { repReply, telemetry, author, quickReplies }
}
```

`capabilities` is how the console degrades instead of breaking. `repReply: false`
disables the composer with a stated reason; `telemetry: false` collapses the
observability panel to client-observed timing. The mock advertises `repReply` and
`telemetry` as **true** so the UI can be built and demonstrated; the future
`salespilot` adapter will advertise what the backend actually supports.

## Data models

Normalised at the adapter boundary, so views never touch raw payloads.

```js
// One inbox row
ConversationSummary = {
  id, name, score, priority, state, product,
  humanTakeover, lastMessagePreview, lastMessageAt,
  customerMessageCount,
}

// Transcript entry — the authorship axis is resolved here, once
Message = {
  id, clientMessageId, role,          // 'customer' | 'agent'
  origin,                             // 'customer' | 'ai' | 'human' | 'system'
  text, ts, repName,
}

// interface-v1.md §5.3
AgentRun = {
  runId, clientMessageId, trigger, status,      // 'ok' | 'degraded' | 'error'
  startedAt, durationMs, customerMessageCount,
  steps:     [{ index, name, kind, durationMs, status }],
  llmCalls:  [{ index, purpose, model, durationMs,
                promptTokens, completionTokens, totalTokens,
                cost: { amount, currency },
                input: { chars, content }, output: { chars, content } }],
  toolCalls: [],
  totals: { agentStepCount, llmCallCount, toolCallCount, totalTokens,
            cost: { amount, currency } },
  clientObserved: { durationMs, status },       // harness only
}
```

`origin` resolves `role` and `author` into one axis exactly once, at the adapter:

```js
const origin = role === 'customer' ? 'customer' : (author ?? 'ai');
```

Per `interface-v1.md` §1.2, `author` is absent for older data, and absent means
`ai`. Views read `origin` and never re-derive it.

**Counter naming.** The store uses `customerMessageCount`, never `turns`. The
adapter renames the backend's `turns` on the way in, which confines the misleading
name to one line of code.

## Store

```js
state = {
  route:        'inbox' | 'cases' | 'harness',
  selectedId:   string | null,

  inbox:   { status, items: [], counts: { HIGH, MEDIUM, LOW } },
  conversation: { status, opportunity, messages: [], linkedCase },
  runs:    { status, items: [], selectedRunId },
  cases:   { status, items: [], openCount },
  compose: { draft: '', inFlight: false, error: null },
  transition: { caseId: null, inFlight: false, error: null },

  harness: { deviceReady, transport, scenario, customerId, customerName,
             timeline: [], selectedEntryId },

  capabilities: { repReply, telemetry, author, quickReplies },
}
```

Inbox ordering is presentation only: sort by `score` descending, nulls last. The
score itself is never touched, and priority counts tally the backend's `priority`
strings rather than re-banding numbers — the thresholds live in backend config and
duplicating them here would be a second source of truth.

## Components

```
frontend/admin/
├── index.html
├── css/{tokens.css, app.css}
└── js/
    ├── main.js            boot, hash routing, wiring
    ├── config.js          apiBase, transport, operator, intervals, flags
    ├── strings.js         all copy, plus product/signal/state label maps
    ├── store.js
    ├── identity.js        initials + deterministic colour from id
    ├── format.js          time, duration, tokens, cost, currency
    ├── gateway/{index.js, mock.js, salespilot.js}
    └── views/
        ├── nav.js             three destinations, open-case badge
        ├── inboxList.js       left column, selection
        ├── transcript.js      messages with origin labels
        ├── repComposer.js     human reply, gated
        ├── intelligence.js    state, score dims, histories, NBA, case
        ├── observability.js   run timeline, steps, llm calls, totals
        ├── cases.js           case cards, real transitions
        └── harness.js         device iframe + debug panel
```

`transcript.js` and `observability.js` are shared between the Inbox route and the
Harness route, which is why the harness needs no chat implementation of its own.

## Identity

`opportunity_id` is the key; `customer_name` is a label. The backend keys
opportunities on id alone, so two customers may share a name, and a name is
written once at creation and never updated. The console therefore:

- shows the id on every inbox row and in the conversation header;
- derives avatar initials from the name but the avatar colour from a hash of the
  id, so two customers called Sarah look different;
- never uses the name as a lookup key or a React-style render key.

## Event flows

### Open a conversation

```
row activated
  └─ store.conversationRequested(id)      → workspace loading
  └─ gateway.getConversation(id)
       ├─ ok  → store.conversationLoaded({ opportunity, messages, linkedCase })
       │         └─ if capabilities.telemetry → gateway.listAgentRuns({ opportunityId: id })
       │                                     → store.runsLoaded(items)
       └─ err → store.conversationFailed(message)
```

### Case transition — the only mutation outside replying

```
take-over activated
  └─ store.transitionStarted(caseId)     → that card's controls disabled
  └─ gateway.updateCaseStatus(caseId, 'TAKEN_OVER')
       ├─ ok  → store.transitionSucceeded(updatedCase)   ← from the response body
       │         ├─ recompute openCount and the nav badge
       │         └─ if it is the open conversation, enable the composer
       └─ err → store.transitionFailed(message)          → card unchanged, inline error
```

Never optimistic. A takeover that appears to succeed but did not is worse than a
slow one, because two people could believe they own the same customer. The new
status comes from the response body, not from the value requested.

### Human reply

```
composer submit
  └─ guard: capabilities.repReply && opportunity.humanTakeover   → else disabled
  └─ store.replyStarted(clientMessageId)
  └─ gateway.sendRepReply({ id, text, repName: config.operator.name, clientMessageId })
       ├─ ok  → store.replyAppended(message)   → origin 'human'
       └─ err → store.replyFailed(message)     → draft preserved, inline error
```

The draft survives failure. Losing a representative's typed reply is worse than
showing an error.

## Harness

### Why an iframe

The route embeds `../customer/index.html` in an iframe rather than importing the
customer modules. Three reasons:

1. It is literally the shipped customer app, unmodified — a device, not a replica.
2. The customer app's CSS sets global `html` and `body` rules; importing it would
   leak those into the console and require scoping every selector.
3. The compliance invariant holds structurally. Sales intelligence renders in the
   left panel; the iframe contains an app that has no shape for it. Isolation, not
   discipline.

The iframe is sized to device dimensions (400×844), which puts the customer app
below its 600px breakpoint so it renders its full-viewport mobile layout. The
console draws the bezel.

### Protocol

`postMessage`, same-origin, explicit target origin, origin validated on receipt.
Both apps must therefore be served from one HTTP origin — which ES modules already
require, so this adds no deployment constraint.

```js
// device -> console
{ source: 'salespilot-customer', type: 'ready',     payload: { transport, customerId } }
{ source: 'salespilot-customer', type: 'exchange',  payload: { clientMessageId, durationMs, status } }
{ source: 'salespilot-customer', type: 'state',     payload: { customerMessageCount, humanTakeover, connection, messageCount } }

// console -> device
{ source: 'salespilot-admin', type: 'reset' }
{ source: 'salespilot-admin', type: 'receive', payload: { text, author, repName } }
{ source: 'salespilot-admin', type: 'inject',  payload: { text } }
```

`receive` delivers an inbound message to the device — used to show what a **human
representative's** reply looks like from the customer's side. When `author` is
`human` the device also flips into takeover, because that is what the backend's
semantics imply. This is the one thing no other surface can show: the Inbox
composer writes through the backend rep-reply path. In live mode the customer
device receives that message through takeover-only incremental polling; in mock
mode `receive` remains a direct visual-test command because the two adapters share
no persistence.

`inject` drives the device as if the customer had typed. **No control exposes it**,
because typing in the device is the identical action; it is retained for scripted
scenario replay (stretch A3).

**Configuration is not a message.** The console reconfigures the device by
rebuilding the iframe `src` with new query parameters — `transport`,
`customerId`, `customerName`, `scenario` — which the customer app reads through
the allow-list in its `config.js`.

The alternative, a `configure` message applied to a live app, was rejected:
changing transport means rebuilding the gateway, and mutating a running one risks
carrying stale connection, capability and conversation state across the switch. A
reload rebuilds from nothing, which is the cheaper thing to reason about.
Requirement 6.6 is still met, because the *console* never reloads — only the
device inside it does.

Handshake: the console arms a timeout when it sets the iframe `src`, and treats
the device as connected only on `ready`. `reset` and `inject` are disabled until
then, so no command is lost to a race. A device reload repeats the whole
sequence.

### Telemetry routing — the important part

The device payload is deliberately tiny and non-sensitive: a correlation id, a
client-observed duration, a status. **Telemetry does not travel through the
customer app**, because under `interface-v1.md` §2 the customer surface has no
shape for it — the app never receives it in the first place.

```
1. device   ──▶ customer surface        POST with client_message_id
2. device   ──postMessage──▶ console    { clientMessageId, durationMs, status }
3. console  ──▶ admin surface           listAgentRuns({ clientMessageId })
4. console renders the debug timeline
```

`client_message_id`, added to the backend for idempotency, doubles as the
telemetry correlation key. No new identifier is needed.

### Required change to the customer app

Small, and inert when not embedded:

- `js/telemetry.js` — no-ops unless `window.parent !== window`; emits `ready`,
  `exchange`, `state`.
- `js/config.js` — accept overrides from URL parameters for transport, customer id,
  customer name and API base, through an explicit allow-list so a crafted link
  cannot reach anything else. Useful independently of the harness, and the
  mechanism configuration travels on.
- a message listener for `reset` and `inject`, which reuses the existing
  programmatic send path rather than synthesising input events.

Requirement 6.10 is the hard constraint: standalone, the customer app must emit
nothing at all.

## Error handling

| Condition | Store effect | Operator sees |
| --- | --- | --- |
| Inbox load fails | `inboxFailed` | Error with retry; no stale rows shown as current |
| Conversation load fails | `conversationFailed` | Error with retry; list still usable |
| Runs load fails | `runsFailed` | Observability panel error; transcript unaffected |
| Case transition fails | `transitionFailed` | Inline error on that card only |
| Reply fails | `replyFailed` | Inline error, draft preserved |
| Device never sends `ready` | `deviceReady: false` | Timeout notice with a reload control |
| Capability unavailable | — | Control disabled with the reason stated |

Stale data is never presented as current. Showing a status code is acceptable here
because the audience is internal; stack traces still go only to the console.

## Security notes

- No authentication. Anyone reaching the console can read every transcript and
  take over or close any case. Documented demo limitation; not to be disguised.
- All backend text — names, case summaries, escalation reasons, transcripts,
  knowledge facts, and **model prompts** — renders through `textContent`. Prompts
  echo customer wording and are untrusted data.
- Prompt and output content is displayed only when the backend chooses to expose
  it. When withheld, the console shows character counts and says content is not
  exposed; it never attempts to reconstruct it.
- `postMessage` never uses `*` as a target origin, and every received message is
  origin-checked and shape-checked before use.
- Transcripts and cost data are internal. The console should not be exposed beyond
  the operator's own machine or network.
- No outbound request to any origin other than the configured `apiBase`.

## Testing strategy

Manual and scripted, no test framework, consistent with the customer app. A JS
test runner would mean a build step.

1. **Mock walkthrough.** All three routes against the mock adapter, including a
   case transition, a human reply, and a degraded agent run.
2. **Degradation check.** Force `capabilities.repReply` and
   `capabilities.telemetry` to false and confirm the console stays usable with
   stated reasons rather than blank panels or zeros.
3. **Harness handshake.** Reload the device mid-session and confirm configuration
   is reapplied; send a message and confirm a timeline entry appears and resolves
   to a run.
4. **Isolation check.** Confirm no sales intelligence renders inside the iframe,
   and that opening the customer app standalone emits no `postMessage` at all.
5. **Identity check.** Two conversations with the same `customer_name` and
   different ids must be distinguishable by id and avatar colour.
6. **Accessibility baseline.** Keyboard-only pass, table semantics, no
   colour-only status.

Backend tests are out of scope and untouched.
