# Design — Admin console UI

## Overview

A small three-view single-page app in `frontend/admin/`. Same architecture as the
customer chat — `views → store → gateway` in one direction — so the two apps stay
mentally interchangeable, but the transport is simpler: there is only one backend,
so no adapter family is needed.

```
views/  ──reads──▶  store  ──calls──▶  api.js  ──HTTP──▶  /api/*
   └────dispatch intent──┘◀──────plain objects─────┘
```

The console is **read-only except for one mutation**: case status transitions. That
single write is what makes it more than a dashboard, and it must be real — the
legacy console's takeover button is cosmetic and that mistake is not repeated here.

The console displays sales intelligence in full. This is the opposite of the
customer chat, which discards it at the adapter boundary. Both rules exist for the
same reason: put the audience boundary in one place and make it structural.

## Architecture

```
frontend/admin/
├── index.html            # shell: nav + three view containers
├── css/
│   ├── tokens.css        # shared scale with the customer app + data-UI additions
│   └── app.css           # nav, table, cards, badges
└── js/
    ├── main.js           # boot, routing, wiring
    ├── config.js         # apiBase, intervals, feature flags
    ├── strings.js        # all user-facing text, incl. state/signal/product labels
    ├── store.js          # state + actions + subscribe()
    ├── api.js            # the only module that calls fetch
    └── views/
        ├── nav.js        # three destinations + open-case badge
        ├── queue.js      # priority counts + sorted table
        ├── cases.js      # case cards + status transitions
        └── detail.js     # one opportunity in full
```

No build step, no dependencies, ES modules, matching the customer app.

## Components and interfaces

### `api.js`

Thin, typed-by-convention wrappers over the documented endpoints. Nothing else in
the app calls `fetch`.

```js
listOpportunities()            // GET  /api/opportunities   -> { count, items }
getOpportunity(id)             // GET  /api/opportunities/{id}
listCases()                    // GET  /api/cases           -> { count, items }
updateCaseStatus(id, status)    // PATCH /api/cases/{id}      -> case
seedDemoData()                 // POST /api/seed
health()                       // GET  /health
```

`GET /api/dashboard` is deliberately unused. It returns an `items` array identical
to `/api/opportunities` plus a `text` field that is pre-rendered CLI output. Using
the plain list endpoint avoids any temptation to display terminal text in a web UI.

`GET /api/analytics` is unused in the first delivery; it is the basis of stretch
item A1.

### Store

```js
const state = {
  view:        'queue' | 'cases' | 'detail',
  selectedId:  string | null,
  queue:       { status: 'idle'|'loading'|'error', items: [], counts: { HIGH:0, MEDIUM:0, LOW:0 } },
  cases:       { status: 'idle'|'loading'|'error', items: [], openCount: 0 },
  detail:      { status: 'idle'|'loading'|'error'|'notFound', opportunity: null, linkedCase: null },
  transition:  { caseId: null, inFlight: false, error: null },
};
```

Actions: `viewChanged`, `queueLoading`, `queueLoaded`, `queueFailed`,
`casesLoading`, `casesLoaded`, `casesFailed`, `detailRequested`, `detailLoaded`,
`detailFailed`, `transitionStarted`, `transitionSucceeded`, `transitionFailed`,
`seedCompleted`.

`counts` is populated by tallying the backend's `priority` strings, never by
re-banding `final_score` (Requirement 5.2). The thresholds live in the backend's
config; duplicating them here would be a second source of truth that silently
drifts.

### Ordering and normalisation helpers

Two small pure helpers, the only place derived values are allowed:

- **Queue ordering** — sort by `final_score` descending, with null scores last.
  This is presentation ordering, not re-ranking: the score itself is untouched
  (Requirement 1.2, 5.1).
- **Case status normalisation** — uppercase and replace spaces and hyphens with
  underscores, turning `"Taken Over"` into `TAKEN_OVER` (Requirement 2.3). The
  backend serialises title case but accepts either form on write, so normalise on
  read and send canonical tokens on write.

### Views

Each view owns a container element, subscribes to the store, and re-renders its
own subtree. No shared DOM ownership.

- **`nav.js`** — three destinations, active indication, open-case badge hidden at
  zero.
- **`queue.js`** — three priority count cards, then a table with columns:
  customer, state, score, priority, signals, next action, takeover marker. Row
  activation opens detail. Empty state offers seeding.
- **`cases.js`** — one card per case with all fields from the case object, plus
  controls driven by normalised status. Includes the standing note that closing a
  case returns the conversation to the AI (Requirement 2.10).
- **`detail.js`** — identity and flags, the five score dimensions, score history,
  state history, transcript. When the opportunity is under takeover, the linked
  case's reason and recommended action are surfaced at the top.

## Data models

The console consumes the backend's objects as documented in
`docs/backend-contract.md` and does not define its own domain model. It stores what
it receives and reads fields directly.

Presentation-only mappings live in `strings.js`:

- Product enum (`essential`, `family`, `plus`, `corporate`, `unknown`) → display
  labels.
- Signal values → short labels for dense table cells, for example
  `Expansion: Family` → `Exp: Family`. The full value is kept as the cell's title
  so nothing is lost.
- Priority bands → badge classes.

The five score dimensions are only available on `POST /api/messages` responses,
not on the opportunity object, which exposes `final_score` and `priority`. The
detail view therefore shows the total and the histories, and shows the dimension
breakdown only when it is available. Recording this here prevents a future
implementer from assuming the breakdown is always present.

## Event flows

### Load queue

```
viewChanged('queue')
  └─ store.queueLoading                → loading state
  └─ api.listOpportunities()
       ├─ ok    → store.queueLoaded(items)   → sort, tally counts, render table
       │                                       or empty state with seed offer
       └─ error → store.queueFailed          → error state, retry control
```

### Case transition — the only mutation

```
take-over activated
  └─ store.transitionStarted(caseId)   → that card's controls disabled
  └─ api.updateCaseStatus(caseId, 'TAKEN_OVER')
       ├─ ok    → store.transitionSucceeded(updatedCase)
       │            ├─ replace the case in state from the response body
       │            └─ recompute openCount and the nav badge
       └─ error → store.transitionFailed(message)
                    └─ card unchanged, inline non-blocking error
```

The display is never updated optimistically (Requirement 2.7). A takeover that
appears to succeed but did not is worse than a slow one, because two people could
believe they own the same customer. The response body is the source of truth for
the new status rather than the value that was requested.

### Open detail

```
row activated
  └─ store.detailRequested(id)          → view switches, loading state
  └─ api.getOpportunity(id)
       ├─ 200 → store.detailLoaded(opportunity)
       │          └─ if human_takeover, find the non-closed case for this id
       │             from the already-loaded case list and attach it
       ├─ 404 → store.detailFailed('notFound')  → not-found state
       └─ err → store.detailFailed(message)     → error state
```

Linking a case to an opportunity is done client-side by matching
`case.opportunity_id` against the opportunity id and taking the one whose
normalised status is not `CLOSED`. The backend maintains one active case per
opportunity, so this match is unambiguous.

## Error handling

| Condition | Store effect | Representative sees |
| --- | --- | --- |
| Queue load fails | `queueFailed` | Error state with retry; no stale rows shown as current |
| Cases load fails | `casesFailed` | Error state with retry |
| Detail 404 | `detailFailed('notFound')` | Not-found state |
| Detail load fails | `detailFailed` | Error state with retry |
| Transition fails | `transitionFailed` | Inline error on that card; nothing else disturbed |
| Seed fails | `queueFailed` | Error state; the endpoint is idempotent so retrying is safe |

Stale data is never presented as current (Requirement 5.3). When a refresh fails,
the view shows an error rather than leaving old rows looking authoritative.

Error text comes from `strings.js`. Unlike the customer app, showing a status code
here is acceptable — the audience is internal — but stack traces still go only to
the console.

## Security notes

- No authentication. Anyone reaching the console can read every customer's
  transcript and take over or close any case. Accepted demo limitation, recorded in
  `product.md` and `docs/backend-contract.md`. Do not add a fake login to paper
  over it.
- All backend text — names, case summaries, escalation reasons, transcripts,
  knowledge facts — renders through `textContent`. Case summaries in particular are
  backend-composed strings containing customer-derived content, so they are treated
  as untrusted data.
- Transcripts contain personal customer messages. The console is an internal tool
  and should not be exposed publicly, even for a demo, beyond the presenter's own
  machine or network.
- No outbound requests to any origin other than the configured `apiBase`.

## Testing strategy

Manual and scripted, no test framework, consistent with the customer app.

1. **Seeded-data walkthrough.** Run `py -3 run.py --serve --seed`, then exercise
   all three views. The three scripted conversations produce at least one HIGH
   priority opportunity and at least one open case, which covers the interesting
   paths.
2. **Transition round-trip.** Take over a case, confirm via
   `curl http://127.0.0.1:8000/api/cases` that the server status actually changed,
   then resolve it and confirm `human_takeover` cleared on the opportunity via
   `GET /api/opportunities/{id}`. This is the check the legacy console would fail.
3. **Failure injection.** Stop the backend mid-session and confirm each view shows
   an error state rather than stale or blank content.
4. **Empty-state check.** Run without `--seed` and confirm the queue offers
   seeding, seeding works, and the view refreshes.
5. **Accessibility baseline.** Keyboard-only pass over navigation, rows and case
   controls; confirm table header semantics and that no status is colour-only.

Backend tests are out of scope and untouched.
