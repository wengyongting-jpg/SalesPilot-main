# Frontend changelog

Record of what changed in each update to `frontend/customer/` and
`frontend/admin/`.

> **This file is updated only on explicit instruction from the repository owner.**
>
> Completing a code change does not authorise an entry here. If work seems worth
> recording, finish the work and report that a changelog entry is pending
> authorisation. Do not create, edit, or append entries otherwise.

## How to write an entry

One entry per authorised update. Newest first. Keep it factual and short — what
changed, why, and anything a reviewer or demo operator needs to know.

```markdown
## <YYYY-MM-DD> — <short title>

**Scope:** customer | admin | both
**Spec tasks:** <task numbers from the relevant tasks.md, if applicable>

### Changed
- <what changed, in behavioural terms>

### Fixed
- <bug, and how it manifested>

### Known issues
- <anything left broken or deliberately deferred>

### Backend dependencies
- <items from docs/backend-contract.md this relies on, and the degradation used
  while they are outstanding>
```

---

## Entries

## 2026-09-22 — Test suite, UI refinements, harness rep-message control

**Scope:** both
**Spec tasks:** `customer-chat-ui` 1–3 · `admin-console-ui` 1–5 (refinements)

Three pieces of work: a frontend test suite, four UI changes you asked for, and a
self-audit of the tests themselves that found real defects in the tests.

### Changed — test suite

- **New suite at `frontend/tests/`**, run with Node's built-in runner. No
  dependency, no install, no build step:

  ```powershell
  cd frontend
  node --test "tests/**/*.test.js"
  ```

  **273 tests, 64 suites, 0 failures, 0.9s.** `frontend/package.json` exists only
  to declare `"type": "module"` so Node can import the apps' ES modules; it has
  no dependencies and browsers never read it.
- **Extracted `customer/js/rules.js`** from `views/messageList.js`. Grouping, tail
  attribution, date-separator placement, the scroll-position test and the
  auto-scroll decision were module-private and checkable only by eye. They are now
  pure functions, which is what made them testable — and separates the rules from
  the DOM. `messageList.js` imports them; behaviour is unchanged.
- Tests cover pure logic only: rules, stores, formatting, identity, mock
  adapters, transport selection and the telemetry protocol. There is no DOM
  environment, because adding one would add a dependency.

### Changed — UI

- **Removed "Signed in as Alex"** from under the Inbox reply box. It duplicated
  the sidebar. Dropped the now-unused `config` import from `repComposer.js`.
- **Inbox restyled from lines to containers.** The three columns are now separate
  rounded panels separated by gaps instead of `border-right`/`border-left`. Rows
  lost their `border-bottom` in favour of spacing, a rounded hover and a filled
  rounded selected state. Header and panel-tab rules became a soft
  `box-shadow: 0 1px 0`. History and step rows became tinted rounded blocks.
  Radii increased: `sm` 4→6, `md` 8→10, `lg` 12→16, new `xl` 20, `pill` → 999px.
- **Unified scrollbars across both apps.** A 6px floating thumb with a fully
  transparent track and no frame, tokenised so the two apps agree. Standard
  properties for Firefox, `::-webkit-scrollbar-*` for Chromium and WebKit.
- **Replaced the harness "Send as customer" control with "Send as business —
  human representative".** Your point was right and sharper than UI redundancy:
  the old control had no capability of its own, since typing in the device on the
  right is the identical action. The new control does the one thing nothing else
  in the product can — show the customer's view of a human reply — via a new
  `receive` postMessage command that renders an inbound message attributed to a
  representative and flips the device into takeover. Fixed a stale
  `timelineEmpty` string that still referenced the removed control.
- The `inject` command is retained in the protocol with **no UI exposing it**,
  for scripted scenario replay (stretch A3).

### Changed — mock latency is now overridable

Both mock adapters take a latency scale. **The default is unchanged (`1`), so the
demo feel is identical**; the suite runs at `0`. This is the one change made to
app code for testability, and it was explicitly approved.

### Fixed

- **Test suite wall time cut from ~26s to 0.9s.** The suite was sitting inside
  `setTimeout`, exercising the mock's latency simulation rather than any logic
  under test. `customer/mock.test.js` alone went 15.7s → 0.32s;
  `admin/mock.test.js` 10.5s → 0.65s.
- **A real bug found while doing the above.** The first version of the customer
  mock read its latency override *lazily*, inside `send()`/`loadHistory()`. Those
  are async, so they sampled `window.location.search` after the test helper had
  already restored the real `window` — the override silently had no effect and
  every test still waited 700–1200ms. Fixed by reading it once at construction
  time, alongside `readScenario()`. Two regression tests now time this with a
  real clock rather than merely asserting the parameter is accepted.

### Fixed — defects in the tests themselves

Found by auditing the tests rather than the code, at your request. Each of these
made the suite weaker or more fragile than its green result implied.

- **A tautological test.** `identity.test.js` had a test named "is derived from the
  id, not the name" whose assertion was
  `avatarColour('C-1024') === avatarColour('C-1024')` — a restatement of the
  previous test that could not fail for the reason its name claimed. Worse than no
  test, because it manufactured confidence. Replaced with an assertion on the
  function's actual arity and contract.
- **Locale-dependent assertions that passed by luck.** `count(1234567)` was
  compared against the literal `'1,234,567'`. Verified across locales: en-US and
  zh-CN pass, **de-DE produces `1.234.567` and would fail**, fr-FR groups with a
  narrow no-break space. The tests were asserting Node's `Intl` output rather than
  our own logic. Both `count` and `chars` now strip non-digits and compare the
  digits, plus assert that grouping happened at all.
- **An assertion coupled to a config default.** `config.test.js` asserted
  `sendTimeoutMs === 30000`, so a legitimate timeout change would have failed a
  test about URL allow-listing. Now reads the untouched default as a baseline and
  asserts the override did not land.
- **Fixture-quality checks mixed into behavioural tests.** Checks such as "score
  dimensions sum to the total" verify hand-authored fixture data, not code. Moved
  into a clearly labelled `fixture data-quality checks (not behavioural)` block so
  a failure reads as "the fixture numbers now disagree" rather than "the code
  broke". Added one more: every conversation claiming takeover must have a
  non-closed case.
- **Coverage gaps closed.** Transport selection in both apps had no tests at all,
  despite mapping to requirement 9.1 — including the unknown-transport throw. The
  WhatsApp stub's explicit refusal to work is **requirement 9.4** and was
  untested. `format.shortWhen` and `format.dateTime` had no tests. All now
  covered by two new `gateway.test.js` files and additions to `format.test.js`.
- **Documented the fake-element limitation.** The `applyAvatar` test uses a
  hand-rolled stub, not a real `Element`. Now states explicitly what it does not
  prove: that a real element accepts the colour string, that anything is painted,
  or real attribute-reflection semantics.

### Verified

- Full suite green on three consecutive runs (273/273), not a single lucky pass.
- **Mutation testing to confirm the suite has teeth**, rather than trusting the
  count. Five deliberate defects introduced and reverted, all caught:
  the grouping window `>` → `>=` (1 failure); dropping the author comparison
  (2); auto-scroll always on (2); **absent cost silently becoming `0.0000`**
  (caught); **priority re-banded locally from the raw score instead of trusting
  the backend** (1). The last two are exactly the defect classes this project
  keeps guarding against.
- Locale independence of the rewritten assertions confirmed against en-US, de-DE,
  fr-FR and zh-CN.
- Encoding integrity: all 55 frontend source files scanned, zero replacement
  characters. ESM syntax check on every touched app module.
- `git status` confirms no change under `salespilot/`, `tests/`, `data/`,
  `run.py` or `requirements.txt`.

### Known issues

- **I corrupted three source files during the mutation experiment and had to
  repair them.** Using PowerShell `Get-Content -Raw` / `Set-Content` to patch
  files round-tripped UTF-8 through the console's GBK default, turning em dashes
  into `U+FFFD` and **swallowing a closing quote**, which broke `format.js`
  outright. Five of the nine corrupted spots were live `return '—'` values, not
  comments, so behaviour changed. Repaired via Node and verified clean. Lesson
  applied: file edits now go through the editing tools, never a shell text
  round-trip.
- Three mistakes of my own were found and fixed while writing these tests, all
  before hand-off: `new Date(null)` is the 1970 epoch, not an invalid date, so an
  "absent value" assertion was testing the wrong thing; the WhatsApp stub throws
  *synchronously*, so `assert.rejects` was the wrong matcher; and
  `node:assert/strict` provides `doesNotMatch`, not `notMatch`.
- **`format.shortWhen` returns `''` for an invalid date** while `time`,
  `dateTime`, `duration` and `count` all return an em dash. Asserted as-is so
  harmonising it later is a deliberate, visible change — but it is an
  inconsistency in the module.
- **View modules remain untested** — 18 of them, plus `admin/js/dom.js`. All
  require a DOM, and `dom.js` matters most because its `text` versus `html`
  distinction is the XSS boundary. Blocked by the no-dependency rule, not
  overlooked.
- Visual and interactive behaviour is still unverified by me: bubble geometry,
  the restyled Inbox proportions, scrollbar appearance, animation feel,
  breakpoints, focus rings, and the iframe handshake all need a human pass.
- Slice 6 outstanding in both apps: accessibility pass, responsive pass, and all
  stretch items.

### Backend dependencies

Unchanged from the entry below. The customer mock still advertises
`idempotency: false` even though backend item 1 shipped, so the retry duplicate
warning still appears in mock mode; it will be corrected when the customer
`salespilot` adapter lands.

---

## 2026-09-22 — Customer chat (slices 1–3) and admin console (slices 1–5)

**Scope:** both
**Spec tasks:** `customer-chat-ui` 1–3 · `admin-console-ui` 1–5

Both apps are vanilla HTML, CSS and ES modules with no build step, no npm and no
CDN. Both run entirely on a mock transport and require no Python server. No
backend file was touched.

Serve from `frontend/` so the two apps share one origin, which the harness needs:

```powershell
py -3 -m http.server 8123
#   http://127.0.0.1:8123/customer/index.html
#   http://127.0.0.1:8123/admin/index.html
```

### Changed — customer chat (`frontend/customer/`, ~2530 lines)

- **Message rendering.** Bubbles with a tail on the first message of a run only,
  grouping within 60 seconds, date separators labelled Today / Yesterday /
  absolute, inline 24-hour timestamps, centred system messages, and emoji-only
  messages rendered enlarged without a bubble. All message text goes through
  `textContent`; URLs are deliberately not linkified.
- **Delivery ticks anchored to real events**, not timers: clock while the request
  is in flight, single tick on HTTP 2xx, double blue tick once the reply has
  rendered. These are three distinct store transitions.
- **Send flow.** Optimistic append, mic-to-send glyph swap, Enter sends and
  Shift+Enter inserts a newline, auto-grow to five lines, text-emoticon
  conversion, trim-and-reject-empty. The composer stays editable while a send is
  in flight so typed text is never lost.
- **Retry reuses the original `clientId`**, so a retried message returns to the
  same bubble instead of creating a second one.
- **Typing indicator** in the incoming position plus a header typing status,
  removed the moment the reply lands or the send fails.
- **Scrolling.** Auto-scroll only within 80px of the bottom; otherwise a
  jump-to-latest control appears with an unread count. Sending always scrolls.
- **States.** Welcome, loading skeleton, and history error that preserves already
  rendered messages.
- **Transport adapters** behind one interface: `mock` (default), `salespilot`
  (stub), `whatsapp` (documented shape-only stub that throws). Capabilities are
  detected from what the transport actually returns rather than assumed.
- **Offline banner** driven by `navigator.onLine`, and a demo reset control. Both
  pulled forward from later slices because they are backend-independent.
- **Harness support.** `telemetry.js` is inert unless the app is embedded in an
  iframe; `config.js` accepts URL overrides through an allow-list of four keys
  with transport validated against an enum.

### Changed — admin console (`frontend/admin/`, ~4750 lines)

- **Three routes** — Inbox (landing), Cases, Harness — with hash routing so the
  view survives a reload.
- **Inbox.** Conversations ordered by score descending with nulls last. Every row
  carries the opportunity id, and avatar colour is hashed from the **id** rather
  than the name, so two customers legitimately named the same are visually
  distinct. Takeover is marked with text, not colour alone. There is deliberately
  no unread count: no read state exists anywhere in the system.
- **Transcript.** Origin — customer, AI assistant, representative, system — is
  resolved once at the adapter from `role` plus `author` and labelled in text.
- **Rep composer.** Enabled only when the transport supports a human reply *and*
  the conversation is under takeover; otherwise disabled with the specific reason
  stated rather than failing on submit. A failed send preserves the draft.
- **Intelligence panel.** State, product, priority, total score, the five score
  dimensions when available, signals, the three risk flags, expansion, next best
  action, the linked open case, and score and state histories. Nothing is
  recomputed: priority counts tally the backend's own strings rather than
  re-banding numbers.
- **Observability panel.** Run timeline, ordered steps with kind and duration,
  per-model-call model, tokens, cost and duration, input and output content with
  character counts, and per-run and per-conversation totals.
- **Cases.** Real, non-optimistic status transitions that update from the response
  body rather than the requested value, with in-flight controls disabled and
  inline errors on failure. Resolving states up front that it returns the
  conversation to the AI.
- **Harness.** The **unmodified customer app** embedded in an iframe as a device,
  with a debug panel beside it. `postMessage` uses an explicit target origin and
  every inbound message is checked for origin, source tag and frame. A `ready`
  handshake with a timeout guards configuration, and `reset` and `inject`
  commands drive the device. Agent telemetry is fetched by the console from the
  admin surface and joined on `clientMessageId`; it is never routed through the
  device.

### Fixed

- Nothing in pre-existing code. Both apps are new, and the legacy console in
  `salespilot/static/` was left frozen and untouched.

### Verified

- 34 modules pass ESM syntax checking.
- Customer logic: 27 assertions covering the three-stage tick progression, retry
  reusing one bubble, deduplication on `id ?? clientId`, unread counting only
  when scrolled away, idempotent takeover system messages, chip suppression under
  takeover, and reset. Plus 11 assertions on the rendering fixture confirming it
  spans two calendar days, groups same-author same-minute messages, does **not**
  group different-author same-minute messages, and carries literal HTML, a URL, an
  emoji-only message and a system message.
- Admin logic: identity disambiguation for two customers named Sarah, score-desc
  ordering, priority tallying, the four-way origin axis, null score dimensions
  handled without fabrication, `toolCalls` empty with a `retrieval` step present
  and no step claiming to be a tool, `llmCallCount` counting extraction *and*
  generation, a degraded run naming its step, withheld content exposing character
  counts only, rule-only runs reporting absent cost rather than zero, canonical
  case status transitions, closing a case clearing takeover, and drafts surviving
  a failed reply.
- Harness: standalone telemetry emits **nothing at all**; embedded telemetry posts
  to an explicit origin with no `postMessage(..., '*')` anywhere in the repository;
  the `exchange` payload contains exactly `clientMessageId`, `durationMs` and
  `status`; serialising the whole channel and searching for `prompt`, `token`,
  `cost`, `score`, `priority` and `next_best_action` finds none of them; the URL
  allow-list rejects an unknown transport and cannot reach `features`.
- Conventions: no inline event handlers, no inline style attributes, no `fetch` in
  any view module, `innerHTML` confined to one helper used only for hand-authored
  icon constants, and no read of a field named `turns` in admin code.
- All static assets serve over HTTP with correct MIME types, and exactly one
  server instance was running.
- A test-assumption error was found and corrected during this work: an assertion
  that replying to Sarah `C-1024` should be rejected with 409 passed only because
  an earlier test had closed her case, making it order-dependent. `C-1024` is
  under takeover in the fixture, matching the real backend, so allowing a reply is
  correct. The gate was re-verified against Michael `C-1025`, who is not under
  takeover. The code was correct; the test was wrong.

### Known issues

- **Not visually verified.** Bubble tail geometry, grouping rhythm, animation
  feel, the three responsive breakpoints, focus rings, and the iframe handshake
  timing were never seen in a browser by the agent that wrote them. They need a
  human pass.
- **No automated coverage of DOM rendering rules.** `startsRun`,
  `formatDateLabel` and `isSameDay` are module-private in `messageList.js`, so
  grouping, tail attribution and separator placement are only checkable by eye. A
  change to the grouping condition would trigger no warning. Scroll behaviour
  cannot be verified headlessly at all. Raised rather than closed, because adding
  tests needs authorisation and a DOM test environment would mean a build step.
- **Harness configuration deviates from `design.md`.** The spec describes a
  `configure` postMessage; the implementation reconfigures by reloading the iframe
  with new query parameters, because switching transport means rebuilding the
  gateway and mutating a live one invites stale state. The console itself never
  reloads, so requirement 6.6 still holds. Syncing the design document is pending
  authorisation.
- **Mock-mode agent runs are synthesised and labelled.** The device and the
  console are separate browsing contexts sharing no backend in mock mode, so a run
  for a just-sent message cannot exist in the console's records. Rather than
  return nothing and leave the correlation mechanism undemonstrable, the mock
  generates a run and flags it `simulated`, and the panel says so. Timeline
  duration and status remain genuinely device-observed.
- **The customer mock still advertises `idempotency: false`.** That mirrored the
  backend when it was written, but backend item 1 has since shipped, so the retry
  duplicate warning is now shown unnecessarily in mock mode. Should be updated
  when the customer `salespilot` adapter lands.
- **Customer slice 4 deferred.** The `salespilot` adapter is still a stub, held
  until `docs/api/interface-v1.md` is frozen, because interface §5.1 moves the
  endpoints it would bind to.
- **Slice 6 outstanding in both apps**: accessibility pass, responsive pass, and
  all stretch items — emoji picker, sounds, background notifications, dark theme,
  analytics, auto-refresh.

### Backend dependencies

Current state of `docs/backend-contract.md` and the degradation in force:

| Item | Status | Degradation now in force |
| --- | --- | --- |
| 1. Message idempotency | **Shipped** | None needed; see the stale mock flag above |
| 2. Quick replies | Not started | No chip row renders |
| 4. Rep reply (P0) | Not started | Admin composer works on mock; disabled with a stated reason against the real backend |
| 6. Visibility tiers (P0) | Not started | Customer adapter would discard sensitive fields client-side |
| 7. `author` field | Not started | Admin treats an absent `author` as `ai` |
| 8. Agent run telemetry | Not started | Observability panel labels metrics "not reported" rather than showing zeros |
| 9. Rename `turns` | Not started | Adapter renames on entry, confining the misleading name to one line |
