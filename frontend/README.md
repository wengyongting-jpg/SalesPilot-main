# SalesPilot frontends

Two independent web applications for the SalesPilot demo:

| App | Audience | Location |
| --- | --- | --- |
| **Customer chat** | The end customer. Sees only the conversation. | `customer/` |
| **Admin console** | Sales staff and operators. Sees everything. | `admin/` |

> ## Current status: no backend, no LLM
>
> **Neither app is connected to the Python backend, and no language model is
> involved anywhere.**
>
> Every screen you see is driven by a **mock transport** — scripted data held in
> the browser. Nothing leaves the page, no API is called, and no model is
> prompted. Specifically:
>
> - The customer app's `salespilot` adapter is a **stub that throws**. Its default
>   transport is `mock`.
> - The admin console's `salespilot` adapter is likewise a **stub that throws**,
>   and advertises every capability as unavailable. Its default is `mock`.
> - The WhatsApp adapter is a **documented shape-only stub**. Selecting it fails
>   loudly on purpose.
> - Replies, opportunity scores, journey states, signals, token counts and costs
>   are all **fixture data**, not model output. Where the admin console shows an
>   agent run that it could not have measured, it labels it `Simulated run`.
>
> This is deliberate, not unfinished work. The backend is mid-refactor, and the
> visibility-tier split in `docs/api/interface-v1.md` §5.1 will move the admin
> endpoints. Binding the adapters now would mean rework, so they wait until
> interface v1 is frozen. See `docs/backend-contract.md` for the gap register and
> the degradation currently in force for each item.

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
| `transport` | `mock` (default), `salespilot`, `whatsapp` |
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

Currently **273 tests, 64 suites, ~0.9s**.

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

Per `AGENTS.md` Rule 2, adding new tests needs the repository owner's agreement.

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

Full rules in `.kiro/steering/frontend-conventions.md`. The load-bearing ones:

- **No business logic in the frontend.** State, signals, score, priority, next
  best action and escalation come from the backend and are displayed, never
  recomputed or re-banded.
- **No dependencies, no build step, no CDN.** Vanilla HTML, CSS and ES modules.
- **All user-facing text lives in `strings.js`;** all colours, spacing, radii and
  durations live in `tokens.css`.
- **No inline event handlers and no inline styles** in HTML.
- **All untrusted text renders via `textContent`.** Message bodies, case
  summaries, knowledge-base facts and model prompts are data, never markup.
- **No WhatsApp trademarks**, logo, wordmark, font or notification sound. The
  assistant is always labelled as AI.
- **One field, one meaning.** The counter for customer messages is
  `customerMessageCount`, never `turns`; see `docs/api/interface-v1.md` §1.1.

## Known limitations

- **No authentication anywhere.** Any visitor to the console can read every
  transcript and take over or close any case; any client can claim any customer
  id. An accepted, documented limitation of the demo — do not disguise it with a
  fake login.
- Delivery ticks reflect client-observed request milestones, not server-issued
  read receipts. The backend has no receipt mechanism.
- Quick-reply chips never render, because the backend field does not exist yet.
- A human representative cannot actually reply through the backend; the Inbox
  composer works against the mock only, and the harness simulates the customer's
  view of a human reply directly.
- All premium figures are fictional indicative demo rates.

## Related documents

| Document | Purpose |
| --- | --- |
| `../AGENTS.md` | Working protocol for every contributor |
| `../docs/api/interface-v1.md` | The authoritative frontend/backend contract |
| `../docs/backend-contract.md` | Gap register: what the backend still owes, with tests |
| `../docs/backend-handoff.md` | Track ownership and priorities |
| `../docs/frontend-changelog.md` | What changed in each authorised update |
| `../.kiro/specs/customer-chat-ui/` | Requirements, design, UX spec, tasks |
| `../.kiro/specs/admin-console-ui/` | Requirements, design, tasks |
