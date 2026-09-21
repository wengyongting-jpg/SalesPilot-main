# Design — Customer chat UI

## Overview

A single-page, zero-dependency chat client in `frontend/customer/`. Three layers,
strictly one-directional:

```
views/  ──reads──▶  store  ──calls──▶  gateway adapter  ──HTTP──▶  backend
   │                   ▲                      │
   └──dispatch intent──┘◀─────normalised──────┘
```

Views never touch the network. Adapters never touch the DOM. The store is the only
mutable state and the only thing both sides know about.

The app holds **no business logic**. Opportunity state, signals, score, priority,
next best action and escalation are backend outputs; the customer UI does not even
display most of them. What the client does own is *presentation* state: delivery
ticks, scroll position, unread count, connectivity, and typing indicator.

## Architecture

```
frontend/customer/
├── index.html              # static shell: frame, header, list, composer
├── css/
│   ├── tokens.css          # design tokens (see ux-spec.md)
│   └── app.css             # component rules
└── js/
    ├── main.js             # boot: build store, gateway, views; wire events
    ├── config.js           # branding, transport choice, intervals, flags
    ├── strings.js          # all user-facing English text
    ├── store.js            # state + reducers + subscribe()
    ├── emoji.js            # emoticon -> emoji, emoji-only detection
    ├── gateway/
    │   ├── index.js        # createGateway(config) -> adapter
    │   ├── salespilot.js   # our FastAPI backend
    │   ├── whatsapp.js     # WhatsApp Cloud API — shape-only stub
    │   └── mock.js         # scripted conversations, no network
    └── views/
        ├── header.js       # avatar, name, AI label, presence/typing
        ├── banner.js       # offline + handoff banners
        ├── messageList.js  # bubbles, grouping, separators, cards, ticks
        ├── composer.js     # input, send/mic control, emoticons
        ├── quickReplies.js # chip row
        └── jumpToLatest.js # floating button + unread count
```

`index.html` contains only static structure and empty mount points. No inline
handlers, no inline styles, no business content.

## Components and interfaces

### Store

Single object, mutated only through named actions, with a subscribe callback for
re-render. No framework, so re-render is explicit: each view subscribes and
updates the DOM it owns.

```js
const state = {
  customer:   { id, name },
  messages:   [],            // normalised Message[], chronological
  pending:    new Map(),     // clientId -> Message, still sending or failed
  assistant:  { typing: false, humanTakeover: false, repName: null },
  quickReplies: [],
  connection: 'online' | 'offline' | 'checking',
  scroll:     { atBottom: true, unread: 0 },
  history:    'idle' | 'loading' | 'error',
  capabilities: { idempotency: false, quickReplies: false, incrementalFetch: false },
};
```

Actions: `sendRequested`, `sendAcknowledged`, `sendFailed`, `replyReceived`,
`historyLoaded`, `historyFailed`, `takeoverChanged`, `connectionChanged`,
`scrollChanged`, `unreadCleared`, `conversationReset`.

`capabilities` is how the frontend stays unblocked. It is populated by the adapter
from what the backend actually returns, and every optional feature reads from it
rather than assuming. See "Capability detection" below.

### Normalised message

Every adapter emits this shape. It is the contract between transport and UI.

```js
{
  id:        string | null,   // server id when available
  clientId:  string,          // always present; generated before send
  direction: 'out' | 'in',
  author:    'customer' | 'ai' | 'human' | 'system',
  text:      string,
  ts:        Date,
  status:    'sending' | 'sent' | 'read' | 'failed',   // meaningful for 'out'
  blocks:    Block[],         // optional rich content
}
```

`Block` is a small tagged union so the message list can render richer content
without the adapter knowing about the DOM:

```js
{ type: 'productCard', title: string, facts: string[], disclaimer: string | null }
{ type: 'disclaimer',  text: string }
```

Deduplication key is `id ?? clientId`. Requirement 8.5 depends on this.

### Gateway interface

```js
createGateway(config) -> {
  async loadHistory(customerId)            -> { messages, humanTakeover }
  async send({ customerId, customerName, text, clientId })
                                           -> { messages, quickReplies, humanTakeover, capabilities }
  async fetchSince(customerId, cursor)     -> { messages }
  async reset(customerId)                  -> void
  async health()                           -> boolean
  readonly name
}
```

Adapters are interchangeable. `send()` returns an array because one send produces
both the echoed outgoing message and the incoming reply.

### `salespilot.js`

Maps `POST /api/messages` onto the gateway interface.

| Backend field | Becomes |
| --- | --- |
| `reply` | incoming message, `author: 'ai'` (or `'human'` when takeover is active) |
| `opportunity.messages` | authoritative transcript for reconciliation |
| `opportunity.human_takeover` | `assistant.humanTakeover` |
| `retrieval.facts` + `detection.product` | `productCard` block |
| `quick_replies` (when present) | `quickReplies` |
| everything else | **discarded** — score, priority, signals, state, NBA, case |

Discarding the sales intelligence is deliberate and load-bearing: it makes it
structurally impossible to leak internal scoring into the customer UI
(Requirement 3.4).

The product card is derivable **today**, with no backend change, because
`retrieval.facts` is already a structured array and `detection.product` names the
plan. The card title comes from the product enum via `strings.js`; facts are
copied verbatim (Requirement 6.2). If any fact mentions a premium, the backend's
disclaimer sentence is attached as the card's `disclaimer`.

Reconciliation strategy: after a successful send, trust
`opportunity.messages` as the transcript, but keep locally-known `clientId`s
attached to the matching outgoing entries so tick state is not lost. Match by
position from the end, since the backend appends and never reorders.

### `whatsapp.js`

A stub, as agreed. It documents the WhatsApp Cloud API shape in comments and the
field mapping to our normalised message, then throws on `send()`:

```js
// WhatsApp Cloud API inbound webhook (abridged):
//   entry[].changes[].value.messages[] = [{ id, from, timestamp, type, text: { body } }]
// Mapping: id -> id, from -> customer.id, timestamp(s) -> ts, text.body -> text,
//          direction 'in', author 'customer'
// Outbound: POST /{phone-number-id}/messages
//   { messaging_product: 'whatsapp', to, type: 'text', text: { body } }
// Statuses arrive as separate webhook events: sent | delivered | read -> status
throw new Error(strings.errors.whatsappNotImplemented);
```

This keeps the seam honest: the shape is recorded so a future implementation has a
target, and nothing pretends to work (Requirement 9.4).

### `mock.js`

Scripted conversations with artificial latency, no network. Drives the whole UI
including takeover and failure paths, which makes the demo independent of the
Python server and gives deterministic material for verification. Scenarios live in
a plain data array, one entry per customer turn with the canned reply, optional
quick replies, and optional takeover flag.

It also exposes a deliberate failure scenario so Requirement 2.7 and 2.8 can be
demonstrated without unplugging the network.

## Capability detection

The frontend must never be blocked by a missing backend feature
(`docs/backend-contract.md` Part B). The rule is: **detect, do not assume.**

| Capability | Detected by | When absent |
| --- | --- | --- |
| `quickReplies` | `quick_replies` present in a response | No chip row rendered |
| `idempotency` | echo of `client_message_id` in the response | Retry still offered, with a warning in its accessible description |
| `incrementalFetch` | `GET .../messages?since=` returns 2xx | Poll the full profile and diff locally |
| rep replies | a message attributed to a human appears | Only AI replies ever observed |

Detection happens on the first successful exchange and is cached in
`state.capabilities`. Absence is never an error and is never surfaced to the
customer.

## State and event flows

### Send

```
composer submit
  └─ store.sendRequested({ text, clientId })       → bubble appears, status 'sending', clock
  └─ store: assistant.typing = true                → typing indicator + header status
  └─ gateway.send(...)
       ├─ 2xx  → store.sendAcknowledged(clientId)  → status 'sent', single tick
       │       → store.replyReceived(messages)     → incoming bubble(s) + blocks
       │       → store: outgoing status 'read'     → double blue tick
       │       → store: assistant.typing = false
       │       → store.quickReplies = […] | []
       └─ error→ store.sendFailed(clientId)        → status 'failed', retry control
               → store: assistant.typing = false
```

The `sent` → `read` progression is two distinct store transitions even though they
usually land in the same tick of the event loop. Keeping them separate is what
makes the tick semantics real rather than a timer.

### Retry

```
retry activated
  └─ store.sendRequested({ reuse: clientId })      → same bubble returns to 'sending'
  └─ gateway.send({ ..., clientId })               → same clientId ⇒ backend can dedupe
```

No new bubble is created (Requirement 2.8). Whether the server actually
deduplicates depends on Part B item 1; the client behaves correctly either way.

### Takeover

```
response.humanTakeover flips false → true
  └─ store.takeoverChanged(true)
       ├─ system message appended  ("a representative is now handling this")
       ├─ banner shown
       ├─ header switches to human representative
       ├─ quickReplies cleared and suppressed
       └─ polling starts
```

Polling only runs while takeover is active (Requirement 8.7). Outside takeover
nothing else can write to the conversation, so polling would burn requests for
nothing. This is a correction to the naive "poll every 2 seconds always" default.

### Connectivity

`navigator.onLine` events flip the banner immediately; a periodic `health()` check
catches a server that is down while the browser still believes it is online. On
recovery the banner clears without reload. Failed messages are never auto-resent
(Requirement 8.4) because with idempotency outstanding, an automatic resend is the
exact path that corrupts `turns` and inflates the engagement score.

## Data models

Config, kept in one module so the demo can be re-pointed without touching views:

```js
export const config = {
  business:   { name: 'CareSure', avatarInitials: 'CS' },
  assistant:  { label: 'AI Assistant', aiDisclosure: true },
  customer:   { id: 'C-2001', name: 'Sam' },
  transport:  'salespilot',            // 'salespilot' | 'whatsapp' | 'mock'
  apiBase:    '',                      // same-origin when served by FastAPI
  pollIntervalMs: 2000,                // used only during human takeover
  healthIntervalMs: 15000,
  features: { demoMode: true, sounds: false, notifications: false, darkMode: false },
};
```

Product display names map from the backend's product enum (`essential`, `family`,
`plus`, `corporate`, `unknown`) to labels in `strings.js`. `unknown` suppresses
the card entirely.

## Error handling

| Condition | Store effect | Customer sees |
| --- | --- | --- |
| Send returns non-2xx | `sendFailed` | Failed bubble, retry control |
| Send times out | `sendFailed` | Same |
| History load fails | `history = 'error'` | Error state with retry, existing messages kept |
| Health check fails | `connection = 'offline'` | Offline banner |
| `whatsapp` adapter selected | throws at boot | Explicit configuration error, not a blank screen |
| Malformed response | `sendFailed` | Failed bubble; details to console only |

No backend detail, status code, or stack trace is ever shown to the customer;
`strings.js` holds one generic message per class of failure. Diagnostics go to the
console.

Timeouts use `AbortController` with a configured budget. A slow LLM-backed reply
is a legitimate slow path, so the send timeout is generous rather than aggressive.

## Security notes

- There is no authentication; the `customer_id` is client-supplied. Any client can
  read or reset any conversation. Recorded as an accepted demo limitation in
  `product.md` and `docs/backend-contract.md`; not to be silently "fixed" here.
- All backend-supplied text — replies, facts, disclaimers, rep names — is rendered
  through `textContent`, never `innerHTML`. Knowledge-base content is data, not
  markup.
- URLs in message text are deliberately not linkified (Requirement 1.9), removing
  a click-through vector from model or knowledge-base output.
- No outbound requests to any origin other than the configured `apiBase`.

## Testing strategy

No test framework is introduced; that would mean a build step. Verification is
scripted and manual, which suits the demo scope.

1. **Mock-adapter walkthrough.** Each scripted scenario exercised end to end. This
   is the primary regression check and needs no server.
2. **Per-slice acceptance checks.** Every task in `tasks.md` carries a concrete
   observable check tied to numbered requirements.
3. **Live integration.** Against `py -3 run.py --serve --seed`, confirming the
   documented response shape is consumed correctly.
4. **Degradation check.** With the real backend, confirm absent `quick_replies`
   and absent message ids leave the UI functional — the capability matrix in
   action.
5. **Failure injection.** Mock adapter's failure scenario plus DevTools offline
   mode for banner, retry, and no-duplicate behaviour.
6. **Accessibility baseline.** Keyboard-only pass, focus visibility, accessible
   names, contrast spot-check against `ux-spec.md` values.

Backend tests are out of scope and untouched.
