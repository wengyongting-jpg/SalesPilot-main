# SalesPilot frontends

Two independent web applications for the SalesPilot demo:

| App | Audience | Location |
| --- | --- | --- |
| **Customer chat** | The end customer. Sees only the conversation. | `customer/` |
| **Admin console** | Sales staff and operators. Sees everything. | `admin/` |

> ## Current status: connected backend, optional LLM
>
> **Both apps are connected to the rebuilt Python backend by default.**
>
> The normal transport is `salespilot`, targeting `http://127.0.0.1:8000`.
> The backend can run visibly offline with rule-based extraction and template
> replies, or use the configured OpenAI-compatible provider. Specifically:
>
> - The customer app uses the customer-tier message and conversation endpoints.
> - The admin console uses the admin queue, case, reply and telemetry endpoints.
> - A separate `mock` transport remains available for fixture-only development.
> - The WhatsApp adapter is a **documented shape-only stub**. Selecting it fails
>   loudly on purpose.
> - Replies report `generation: "template"` in offline mode and `"llm"` only when
>   a model actually produced the wording.

---

## Running

No build step, no `npm install`, no dependencies. The apps are static files.

They must be served over **HTTP from one origin** — not opened as `file://`.
ES modules are blocked by CORS on `file://`, and the test harness needs a real
origin for `postMessage`. Serve from this directory so both apps share an origin:

```powershell
cd frontend
py -3 -m http.server 8123
```

| URL | What it is |
| --- | --- |
| http://127.0.0.1:8123/customer/index.html | Customer chat, empty conversation |
| http://127.0.0.1:8123/customer/index.html?scenario=rendering | Customer chat with a fixture exercising every rendering rule |
| http://127.0.0.1:8123/admin/index.html | Admin console (lands on Inbox) |
| http://127.0.0.1:8123/admin/index.html#/cases | Admin console, Cases |
| http://127.0.0.1:8123/admin/index.html#/harness | Admin console, test harness |

Check the port is free first, and never start a second instance of the same
server.

### Useful URL parameters — customer app

Only an explicit allow-list is honoured, so a crafted link cannot reach anything
else.

| Parameter | Effect |
| --- | --- |
| `transport` | `salespilot` (default), `mock`, `whatsapp` |
| `customerId` | Which conversation the device represents |
| `customerName` | Display name |
| `scenario` | `fresh` (default) or `rendering` |
| `mockLatency` | Scales the mock's artificial delay. `0` makes it instant |

## Tests

Node's **built-in** test runner. Still no dependency and no build step.

```powershell
cd frontend
node --test "tests/**/*.test.js"
```

Run the suite for the current baseline; older recorded counts may be stale.

`package.json` exists *only* to declare `"type": "module"` so Node can import the
apps' ES modules. It has no dependencies, nothing is ever installed, and browsers
never read it. Do not add dependencies to it, and do not introduce a separate test
framework.

Tests cover **pure logic only**: rules, stores, formatting, identity, mock
adapters, transport selection and the harness telemetry protocol. There is no DOM
environment, because adding one would add a dependency. Logic that needs testing
is therefore extracted into pure modules — `customer/js/rules.js` is the
precedent — rather than left private inside a view.

**View modules are consequently untested** and need a manual browser pass. So does
anything depending on layout: scroll geometry, bubble tails, breakpoints, focus
rings and the iframe handshake.

Per [`AGENTS.md`](../AGENTS.md) Rule 2, adding new tests needs the repository owner's agreement.

## Structure

```
frontend/
├── package.json          "type": "module" only — no dependencies
├── customer/             Customer chat app          (20 files, ~2,690 lines)
│   ├── index.html        Static shell; every mount point filled by a view
│   ├── css/
│   │   ├── tokens.css    Design tokens only
│   │   └── app.css       Component rules
│   └── js/
│       ├── main.js       Boot: wires store ↔ views ↔ gateway
│       ├── config.js     Branding, transport, intervals, URL allow-list
│       ├── strings.js    Every user-facing string
│       ├── store.js      Conversation state; the only mutable state
│       ├── rules.js      Pure presentation rules (grouping, dates, scrolling)
│       ├── emoji.js      Emoticon conversion, emoji-only detection
│       ├── icons.js      Hand-authored inline SVG
│       ├── telemetry.js  Harness channel — inert unless embedded
│       ├── gateway/      Transport adapters: index, mock, salespilot, whatsapp
│       └── views/        header, banner, messageList, composer, jumpToLatest
├── admin/                Admin console               (21 files, ~4,842 lines)
│   ├── index.html
│   ├── css/              tokens.css, app.css
│   └── js/
│       ├── main.js       Boot and hash routing
│       ├── config.js     API base, transport, operator, flags
│       ├── strings.js    All copy plus enum label maps
│       ├── store.js      Console state
│       ├── identity.js   Initials, and avatar colour hashed from the id
│       ├── format.js     Time, duration, tokens, cost formatting
│       ├── dom.js        Element helpers
│       ├── gateway/      index, mock, salespilot
│       └── views/        nav, inboxList, transcript, repComposer,
│                         intelligence, observability, cases, harness
└── tests/                                            (13 files, ~2,269 lines)
    ├── customer/         rules, store, emoji, config, mock, gateway, telemetry
    ├── admin/            format, identity, store, mock, gateway
    └── helpers/          browserStubs.js — minimal window stub, not a DOM
```

## Architecture

Both apps use the same one-directional shape, with no framework:

```
views/  ──reads──▶  store  ──calls──▶  gateway adapter  ──HTTP──▶  backend
   └────dispatch intent──┘◀────────normalised──────────┘
```

Views never touch the network. Adapters never touch the DOM. The store is the only
mutable state.

The two apps are deliberate mirror images at the adapter boundary:

- The **customer** adapter **discards** sales intelligence — score, priority,
  signals, journey state, next best action, case internals — so it cannot reach a
  customer's screen.
- The **admin** adapter **keeps all of it**.

Putting the audience boundary in exactly one place per app makes it structural
rather than a matter of remembering.

## The admin test harness

The harness route embeds the **unmodified customer app** in an iframe as a device,
with a debug panel beside it. It is a real instance, not a replica, which is why
sales intelligence can render in the panel and never inside the device — the app
in there has no shape for it.

Two planes of communication, which must not be conflated:

- **Plane A** — each app talks to the backend independently and they are blind to
  each other. This is the production topology.
- **Plane B** — the console talks to the embedded device over `postMessage`, same
  origin, with an explicit target origin and validation of origin, source tag and
  sending frame. This exists only in the harness route.

Plane B carries a deliberately tiny, non-sensitive payload: a correlation id, a
client-observed duration, a status. Agent telemetry is never routed through the
customer app.

## Conventions

The active conventions are below. The former Kiro-era
[`frontend-conventions.md`](../docs/v0.0/conventions/frontend-conventions.md)
is retained as historical background, not an active instruction file.

- **No business logic in the frontend.** State, signals, score, priority, next
  best action and escalation come from the backend and are displayed, never
  recomputed or re-banded.
- **No dependencies, no build step, no CDN.** Vanilla HTML, CSS and ES modules.
- **All user-facing text lives in `strings.js`;** all colours, spacing, radii and
  durations live in `tokens.css`.
- **No inline event handlers and no inline styles** in HTML.
- **Treat all untrusted text as data.** Render plain text through `textContent`;
  use the controlled Markdown renderer where formatting is required. Never
  insert untrusted content directly as HTML.
- **No WhatsApp trademarks**, logo, wordmark, font or notification sound. The
  assistant is always labelled as AI.
- **One field, one meaning.** The counter for customer messages is
  `customerMessageCount`, never `turns`; see `docs/v0.0/api/interface-v1.md` §1.1.

## Known limitations

- **No authentication anywhere.** Any visitor to the console can read every
  transcript and take over or close any case; any client can claim any customer
  id. An accepted, documented limitation of the demo — do not disguise it with a
  fake login.
- Delivery ticks reflect client-observed request milestones, not server-issued
  read receipts. The backend has no receipt mechanism.
- The customer app polls for representative replies only while human takeover is
  active; this is a demo transport, not a push channel.
- The WhatsApp adapter documents the intended boundary but does not call the
  WhatsApp Cloud API.
- All premium figures are fictional indicative demo rates.

## Related documents

| Document | Purpose |
| --- | --- |
| [AGENTS.md](../AGENTS.md) | Working protocol for every contributor |
| [Documentation index](../docs/README.md) | Current work and historical archive map |
| [Persistence repair plan](../docs/v1.0/persistence-repair-plan.md) | Current proposed backend/evaluation work |
| [Interface v1](../docs/v0.0/api/interface-v1.md) | Frozen historical wire contract; verify current behavior in code |
| [Frontend archive](../docs/v0.0/README.md) | Historical requirements, designs, and changelog |
