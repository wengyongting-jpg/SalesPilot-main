# Implementation plan — Admin console UI

Five slices, all against the **mock transport**. No Python server is required for
any task here, and no backend file is touched.

Serve both apps from one origin so the harness works:

```powershell
py -3 -m http.server 8123   # run from frontend/
#   http://127.0.0.1:8123/admin/index.html
#   http://127.0.0.1:8123/customer/index.html
```

Check the port is free first; never start a second instance of the same server.

---

- [ ] 1. Shell, tokens, mock gateway, navigation
  - Create `frontend/admin/index.html` with the nav and three route containers. No
    inline handlers, no inline styles.
  - Create `css/tokens.css` reusing the shared spacing, radius, duration and
    easing scale from `docs/v0.0/frontend/customer-chat-ui/ux-spec.md`, plus data-UI
    additions: table rows, badges, cards, panel chrome, code/JSON surfaces.
  - Create `js/config.js` (apiBase, transport, operator name, intervals, flags),
    `js/strings.js` (all copy plus state, product, signal and step-kind labels),
    `js/store.js` per `design.md`, `js/identity.js` (initials, id-hashed colour),
    `js/format.js` (time, duration, tokens, cost).
  - Create `js/gateway/index.js`, `js/gateway/mock.js` with three seeded
    conversations mirroring the backend's demo script — Sarah `C-1024`, Michael
    `C-1025`, ABC Pte Ltd `C-1026` — plus a **fourth named "Sarah" with a
    different id** so identity disambiguation is exercised. Stub
    `js/gateway/salespilot.js` so the selector resolves.
  - Build `js/views/nav.js`: three destinations, active indication, open-case
    badge, hash routing in `js/main.js`.
  - _Verify:_ the console opens with no console errors, lands on Inbox, and the
    route survives a reload via the URL fragment. Navigate all three destinations
    by keyboard only.
  - _Requirements: 7.1, 7.2, 7.3, 7.7, 8.1, 8.2, 8.3, 9.1, 9.2_

- [ ] 2. Inbox list and conversation transcript
  - Build `js/views/inboxList.js`: rows sorted by score descending with nulls
    last, each showing name, opportunity id, score, priority, last-message
    preview, and a takeover marker that is not colour-only. Selection state.
    Empty state offering to seed. Refresh control. **No unread count.**
  - Build `js/views/transcript.js`: chronological messages with timestamps and an
    origin label for customer, AI, human representative and system. Resolve
    `origin` once in the adapter; treat absent `author` as `ai`. Render all text
    with `textContent`.
  - Wire loading, error and empty states for both regions.
  - _Verify:_ the two same-named Sarahs are distinguishable by id and by avatar
    colour. A transcript containing `<b>bold?</b>` renders literally. Selecting a
    row loads its transcript; a failed load shows an error without clearing the
    list.
  - _Requirements: 1.1–1.10, 2.1, 2.2, 2.3, 2.4, 8.4, 8.5, 9.3, 9.4, 9.6_

- [ ] 3. Intelligence panel and case transitions
  - Build `js/views/intelligence.js`: state, product, priority, total score, the
    five dimensions when present, main concern, the three risk flags, expansion,
    takeover status, `customerMessageCount`, score history, state history, next
    best action, and the linked open case's reason and recommended action.
  - Never recompute a score, band or ranking. Tally priority counts from the
    backend's `priority` strings.
  - Build `js/views/cases.js`: one card per case with every field; status
    normalised before comparison; controls driven by normalised status; real
    transition requests that are **not** optimistic and update from the response
    body; in-flight controls disabled; inline error on failure; open-case count
    and nav badge refreshed on success; the standing note that resolving returns
    the conversation to the AI.
  - Taking over from the cases route must enable the open conversation's composer
    without a reload.
  - _Verify:_ take over a mock case and confirm the status changes only after the
    adapter resolves; force the mock to reject and confirm the card is unchanged
    with an inline error. Confirm an opportunity with no score shows a placeholder,
    not zero.
  - _Requirements: 3.1–3.8, 5.1–5.10_

- [ ] 4. Human reply and agent observability
  - Build `js/views/repComposer.js`: enabled only when `capabilities.repReply` and
    `opportunity.humanTakeover` are both true, otherwise disabled with the reason
    stated — takeover required, or backend support missing. Operator name from
    config. Draft preserved on failure. Appended message attributed to the human,
    never shown as AI output.
  - Build `js/views/observability.js`: run timeline newest last with trigger,
    start, duration and status; selected run showing ordered steps with kind and
    duration; per model call the purpose, model, duration, prompt, completion and
    total tokens, and cost; input and output content with character length, or
    length alone with an explicit "content not exposed" note; totals including
    `agentStepCount`, `llmCallCount`, `toolCallCount`, tokens and cost; a running
    per-conversation token and cost total.
  - `toolCallCount` renders as zero. Retrieval steps are never presented as tool
    calls. Cost is rendered from the backend's amount and currency and never
    computed locally.
  - A `degraded` run is visually distinct and names the degraded step.
  - _Verify:_ with `capabilities.telemetry` forced false, the panel shows
    client-observed duration and status and labels the rest "not reported" — no
    zeros. With a mock run whose content is withheld, only character counts
    appear. With takeover off, the composer is disabled and says why.
  - _Requirements: 2.5–2.10, 4.1–4.11, 8.6_

- [ ] 5. Harness route
  - Add `js/telemetry.js` to **the customer app**: no-op unless
    `window.parent !== window`; emits `ready`, `exchange`, `state`; explicit target
    origin.
  - Extend the customer app's `config.js` to accept transport, customer id,
    customer name and API base from URL parameters through an allow-list, and add a
    listener for `reset` and `inject` that reuses the existing programmatic send
    path. Configuration travels by iframe `src`, not by message — see `design.md`
    § Harness.
  - Build `js/views/harness.js`: left debug panel, right device iframe at 400×844
    with a console-drawn bezel, loading `../customer/index.html`.
  - Left panel: session controls (customer identity, transport, scenario, reset,
    reload device), live status (connection, takeover, `customerMessageCount`,
    running tokens and cost), the exchange timeline, and the selected entry's run
    detail reusing `observability.js`.
  - Arm a timeout when setting the iframe `src`, treat the device as connected only
    on `ready`, and keep `reset` and `inject` disabled until then. Repeat the whole
    sequence on a device reload. Validate `event.origin`, the source tag and the
    sending frame on every receipt.
  - _Verify:_ send a message in the device and confirm a timeline entry appears
    with a client-observed duration, then resolves to a run. Reload the device and
    confirm configuration is reapplied. Inject a message and confirm the device
    sends it. Open `customer/index.html` standalone with DevTools and confirm **no
    `postMessage` is emitted**. Confirm no score, state or priority renders inside
    the iframe.
  - _Requirements: 6.1–6.12_

- [ ] 6. Polish, accessibility, responsiveness
  - [ ] 6.1 Accessibility pass: accessible names, visible focus, table header
        association, status never colour-only, keyboard operability of navigation,
        rows, case controls, composer and timeline.
  - [ ] 6.2 Responsive pass: three columns at 1200px and above; side panel
        collapses to tabs below 1200px; navigation moves above content below
        900px.
  - [ ] 6.3 **[Stretch]** Analytics view.
  - [ ] 6.4 **[Stretch]** Auto-refresh with last-updated time and pause.
  - [ ] 6.5 **[Stretch]** Harness scenario scripting.
  - [ ] 6.6 **[Stretch]** Dark theme.
  - [ ] 6.7 **[Stretch]** Cost budget alert.
  - _Verify:_ 6.1 by a keyboard-only pass with focus always visible and every
    badge pairing colour with text. 6.2 at 1440px, 1200px, 900px and 600px.
  - _Requirements: 7.4, 7.5, 7.6, 9.5, 9.7, 9.8, A1–A5_

---

## Sequencing notes

Every slice runs on the mock, so none is blocked by the backend refactor.

Slice 4 is the console's reason to exist — it is where the agent becomes
observable. Slice 5 is the most demo-visible. If time runs short, the honest cut
line is after slice 4: Inbox, Cases, intelligence and observability together
already tell the whole story, and the harness can be replaced in a demo by opening
the customer app in a second window.

`js/gateway/salespilot.js` is complete against the frozen `/api/admin/*` contract;
the mock remains for deterministic UI work.

## Definition of done

- Slices 1–5 complete, each verification step performed.
- No console errors or unhandled rejections during a full walkthrough of all three
  routes.
- `git status` shows changes only under `frontend/`, `.kiro/` and `docs/`.
- No score, priority, state or cost recomputed client-side.
- No sales intelligence rendered inside the harness iframe.
- The standalone customer app emits no telemetry.
- The word `turns` appears nowhere in admin code; the adapter renames it on entry.
- `docs/v0.0/frontend/frontend-changelog.md` untouched unless the owner has authorised an entry.
