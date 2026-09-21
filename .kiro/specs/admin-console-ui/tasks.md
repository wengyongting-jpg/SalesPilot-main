# Implementation plan — Admin console UI

Four slices. Each leaves the console runnable. Tasks 1–3 are the **demo-ready
minimum**; task 4 is polish and stretch.

This app is smaller than the customer chat by design. Resist scope growth: search,
filtering, sorting controls, analytics and auto-refresh are explicitly deferred.

Backend files stay read-only. Verification assumes a running seeded backend:

```powershell
py -3 run.py --serve --seed
```

---

- [ ] 1. Shell, navigation, and the queue
  - Create `frontend/admin/index.html` with the nav and three empty view
    containers. No inline handlers, no inline styles.
  - Create `css/tokens.css` reusing the shared spacing, radius and duration scale
    from `.kiro/specs/customer-chat-ui/ux-spec.md`, plus data-UI additions for
    table rows, badges and cards. Create `css/app.css`.
  - Create `js/config.js`, `js/strings.js` including product, signal and priority
    label maps, and `js/store.js` with the state shape and actions from
    `design.md`.
  - Create `js/api.js` wrapping `listOpportunities`, `getOpportunity`,
    `listCases`, `updateCaseStatus`, `seedDemoData` and `health`. This is the only
    module that calls `fetch`.
  - Build `js/views/nav.js` with three destinations, active indication and the
    open-case badge.
  - Build `js/views/queue.js`: three priority count cards, then a semantic table
    with customer, state, score, priority, signals, next action and takeover
    marker. Sort by score descending with null scores last. Tally counts from the
    backend's `priority` values, never by re-banding scores.
  - Implement the queue's loading, error and empty states, with the empty state
    offering demo seeding.
  - _Verify:_ with a seeded backend, the queue lists three opportunities ordered
    highest score first, and the counts match the badges on the rows. Stop the
    backend and reload: an error state appears rather than a blank table. Delete
    all opportunities, reload, use the seed control, and confirm the queue
    repopulates. Navigate between destinations by keyboard only.
  - _Requirements: 1.1–1.9, 4.1–4.4, 5.1, 5.2, 5.3, 5.4, 5.5, 6.1, 6.2, 6.3, 6.4, 6.6_

- [ ] 2. Cases and real status transitions
  - Build `js/views/cases.js` rendering one card per case with id, customer,
    state, product, reason, summary, recommended action, status and creation time.
  - Implement status normalisation so `"Taken Over"` matches `TAKEN_OVER`, and
    drive the available controls from the normalised value: open gets take-over
    and resolve, taken over gets resolve only, closed gets none.
  - Wire the transition through `PATCH /api/cases/{id}` with canonical status
    tokens. Disable that card's controls while in flight. Update from the response
    body, not from the requested value. Never update optimistically.
  - On success, refresh the affected case and recompute the open-case count and
    nav badge. On failure, leave the card unchanged and show an inline error.
  - Display the standing note that resolving a case clears human takeover and lets
    the AI resume autonomous selling on the customer's next message.
  - _Verify:_ take over the seeded open case, then confirm the server really
    changed with `curl http://127.0.0.1:8000/api/cases`. Resolve it, then confirm
    `human_takeover` is false via
    `curl http://127.0.0.1:8000/api/opportunities/C-1024`. Stop the backend and
    attempt a transition: the card must stay unchanged and show an inline error.
    Confirm the nav badge count drops when a case is resolved.
  - _Requirements: 2.1–2.11, 5.1, 5.3_

- [ ] 3. Customer detail
  - Build `js/views/detail.js`: identity and flags, score total and priority, the
    five score dimensions when available, main concern, competitive, churn and
    compliance risk, expansion flags, takeover status, turn count.
  - Render score history chronologically with timestamp, score, state and trigger.
  - Render state history with timestamp, from-state, to-state and the backend's
    reason.
  - Render the transcript with timestamps and explicit author labels for customer
    versus assistant.
  - When the opportunity is under takeover, attach the linked non-closed case by
    matching `opportunity_id` and surface its reason and recommended action at the
    top.
  - Render all backend text through `textContent`. Implement not-found, error and
    missing-score placeholder states.
  - Wire row activation from the queue, and a way back to the queue.
  - _Verify:_ open `C-1024` from the queue and confirm five score-history entries
    and the state walk from Cold Lead through to High Intent with the backend's
    reasons shown. Open a non-existent id and confirm a not-found state. Confirm
    the transcript's author labels are correct and that no message renders as
    markup.
  - _Requirements: 3.1–3.8, 4.5, 5.4_

- [ ] 4. Polish, accessibility, and stretch
  - [ ] 4.1 Accessibility pass: accessible names on every control, visible focus
        rings, table header association, status never conveyed by colour alone,
        full keyboard operability of navigation, rows, case controls and refresh.
  - [ ] 4.2 Responsive pass: navigation alongside content at 900px and above,
        collapsed above content below that, with no overlap and no horizontal
        scrolling of the page.
  - [ ] 4.3 **[Stretch]** Analytics view from `GET /api/analytics` — funnel,
        priority mix, signal frequency, conversion rate.
  - [ ] 4.4 **[Stretch]** Auto-refresh with a visible last-updated time and a
        pause control.
  - [ ] 4.5 **[Stretch]** Representative reply composer in the case view, enabled
        only once the backend provides the rep-reply endpoint from
        `docs/backend-contract.md` Part B item 4.
  - [ ] 4.6 **[Stretch]** Dark theme.
  - _Verify:_ 4.1 by a keyboard-only pass with focus always visible and a check
    that every badge pairs colour with text. 4.2 at 1280px, 900px and 600px. Each
    stretch item verified in isolation without regressing tasks 1–3.
  - _Requirements: 4.3, 4.4, 6.5, 6.7, 6.8, A1, A2, A3, A4_

---

## Sequencing notes

Task 1 needs a running backend to show anything meaningful, so unlike the customer
chat there is no useful server-free phase. Seed once and leave the server running
during development.

Task 2 is the highest-value slice for the demo, because a real takeover is what
distinguishes this console from a static dashboard. If time is short, complete
tasks 1 and 2 fully and treat task 3 as reducible — a detail view showing only
identity, score and transcript still supports the narrative.

Task 4.5 must not be started until the backend endpoint exists. Building a reply
box that cannot send is worse than not having one.

## Definition of done for the slice set

- Tasks 1–3 complete, each verification step performed.
- A case takeover and a case resolution both verified against the API with `curl`,
  not by appearance alone.
- No console errors or unhandled rejections during a full walkthrough.
- No backend file modified; `git status` shows changes only under `frontend/`,
  `.kiro/` and `docs/`.
- No score, priority or state value recomputed client-side.
- `docs/backend-contract.md` updated if any new gap was discovered.
- `docs/frontend-changelog.md` left untouched unless the owner has explicitly
  authorised an entry.
