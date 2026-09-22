# Implementation plan — Customer chat UI

Vertical slices. Each slice leaves the app runnable and demonstrable. Tasks 1–5
are the **demo-ready minimum**; 6–7 are polish and may be dropped without
breaking the demo narrative.

Every task states how to verify it. "Open the app" means opening
`frontend/customer/index.html` directly in a browser, or browsing to it when
served as static files — there is no build step.

Backend files stay read-only throughout. Where a slice meets a backend gap, the
degradation is named and the gap is already recorded in
`docs/backend-contract.md`.

---

- [ ] 1. Skeleton, tokens, and the mock transport
  - Create `frontend/customer/index.html` with the static shell: phone frame,
    header, banner slot, message list, quick-reply slot, composer. Empty mount
    points, no inline handlers, no inline styles.
  - Create `css/tokens.css` with every token from `ux-spec.md` sections 1–6, and
    `css/app.css` with the frame, header, and composer rules plus the three
    responsive breakpoints.
  - Create `js/config.js` and `js/strings.js` from the shapes in `design.md`.
  - Create `js/store.js` with the state object, the named actions, and
    `subscribe()`.
  - Create `js/gateway/index.js` and `js/gateway/mock.js` with one scripted
    conversation. Stub `salespilot.js` and `whatsapp.js` so the selector works.
  - Create `js/main.js` to boot the store, gateway and an empty render pass.
  - _Verify:_ the app opens with no console errors; the frame is centred at
    1280px wide, fills the viewport at 375px, and the composer stays visible at
    both sizes. Changing `config.business.name` changes the header.
  - _Requirements: 9.1, 9.3, 11.1, 11.2, 11.3, 11.4, 14.1, 14.2_

- [ ] 2. Message rendering
  - Build `js/views/messageList.js`: bubbles, alignment, tails on run-leaders
    only, grouping within 60 seconds, date separators with Today/Yesterday, inline
    timestamps, system-message chips.
  - Render all four tick states as inline SVG.
  - Build `js/emoji.js` and apply enlarged rendering for emoji-only messages.
  - Render all text through `textContent`; no linkification.
  - Implement the empty, loading-skeleton and history-error states.
  - _Verify:_ against a mock script containing a same-minute run, a cross-midnight
    pair, an emoji-only message, a system message, and a body containing
    `<script>alert(1)</script>` — the last renders as literal text and executes
    nothing. Tails appear only on the first bubble of each run.
  - _Requirements: 1.1–1.9, 6.5, 12.1, 12.2, 12.3_

- [ ] 3. Send flow, typing indicator, scrolling
  - Build `js/views/composer.js`: mic/send glyph swap, Enter to send,
    Shift+Enter for newline, auto-grow to five lines, trim-and-reject-empty,
    emoticon conversion.
  - Wire the optimistic send path through the store: `sending` → `sent` → `read`
    as three distinct transitions, plus `failed`.
  - Add the typing indicator view and the header typing status.
  - Build `js/views/jumpToLatest.js` with the 80px threshold, unread count, and
    smooth scroll. Sending always scrolls to bottom.
  - Add per-message retry reusing the original `clientId`, creating no second
    bubble.
  - _Verify:_ using the mock adapter's failure scenario, a failed message shows
    the danger tick and retry; retrying reuses the bubble. Scroll up 200px, let a
    mock reply arrive, and confirm the list does not jump and the unread badge
    reads 1. Press Enter and Shift+Enter and confirm the different outcomes.
  - _Requirements: 2.1–2.9, 3.1, 3.2, 3.3, 4.1–4.5, 10.1–10.5_

- [ ] 4. Real backend integration
  - Implement `js/gateway/salespilot.js` against `POST /api/messages`,
    `GET /api/opportunities/{id}`, `DELETE /api/opportunities/{id}`, `/health`,
    using the field mapping table in `design.md`.
  - Discard `score`, `priority`, `signals`, `state`, `next_best_action` and `case`
    at the adapter boundary so they cannot reach the UI.
  - Implement capability detection into `state.capabilities`.
  - Implement reconciliation against `opportunity.messages`, preserving local
    `clientId` and tick state by matching from the end.
  - Deduplicate on `id ?? clientId`.
  - Implement `AbortController` timeouts and map every failure class to the
    generic strings from `strings.js`.
  - _Verify:_ start `py -3 -m backend --serve --seed`, send "How much does CareSure
    Plus cost?" and confirm the reply renders with its disclaimer intact. Search
    the rendered DOM for `45`, `LOW`, `Potential Interest` and `nurtur` — none may
    appear. Send the same message twice and confirm two distinct bubbles with no
    duplicate rendering. Confirm no request goes anywhere other than `apiBase`.
  - _Requirements: 3.4, 3.5, 8.5, 9.2, 9.5, 9.6_

- [ ] 5. Rich content, handoff, connectivity
  - Render `productCard` blocks from `retrieval.facts` plus `detection.product`,
    with verbatim facts, a four-fact cap, and the disclaimer when premiums appear.
    Suppress the card when the product is `unknown`.
  - Build `js/views/quickReplies.js`: up to three chips, send on tap, hide on
    typing, render nothing when the field is absent.
  - Implement the takeover transition: system message, banner, header switch to
    representative, chips suppressed, composer still enabled.
  - Start polling only while takeover is active; stop when it ends. Use
    `fetchSince` when `capabilities.incrementalFetch` is true, otherwise poll the
    profile and diff locally.
  - Implement the offline banner from both `navigator.onLine` and health-check
    failure, clearing on recovery without reload, and never auto-resending failed
    messages.
  - Build `js/views/banner.js` and `js/views/header.js` to their final states.
  - _Verify:_ ask "How much does CareSure Plus cost?" and confirm a product card
    with verbatim facts and a visible disclaimer. Then send "I want to speak to a
    human" and confirm the system message, banner, header change, and absence of
    chips. Toggle DevTools offline and confirm the banner appears immediately and
    clears on reconnect with no automatic resend. Confirm no polling requests
    occur before takeover.
  - _Requirements: 5.1–5.5, 6.1–6.4, 7.1–7.6, 8.1–8.4, 8.6, 8.7_

- [ ] 6. Adapter completion, demo mode, accessibility
  - Complete `js/gateway/whatsapp.js` as a documented stub that throws a clear
    not-implemented error, with the Cloud API payload shape and field mapping in
    comments.
  - Add at least three mock scenarios: nurture, hesitation-then-competitor, and a
    path ending in takeover, plus the existing failure scenario.
  - Add the demo reset control, gated on `features.demoMode`, calling
    `DELETE /api/conversations/{id}` on the `salespilot` adapter.
  - Accessibility pass: accessible names on every control, visible focus rings,
    polite live region on the list, keyboard reachability for composer, send,
    chips, retry and jump-to-latest, contrast spot-check against `ux-spec.md`.
  - Honour `prefers-reduced-motion`.
  - _Verify:_ set `transport: 'whatsapp'` and confirm an explicit error rather
    than a blank screen. Complete every mock scenario end to end. Operate the
    whole app with keyboard only, never losing the focus indicator. Enable reduced
    motion and confirm the typing indicator goes static instead of animating.
  - _Requirements: 9.4, 13.1, 13.2, 13.3, 13.4, 14.3–14.7_

- [ ] 7. Polish and stretch items
  - [ ] 7.1 Animation pass against `ux-spec.md` section 6 — pop-in, glyph swap,
        tick cross-fade, chip and banner transitions.
  - [ ] 7.2 **[Stretch]** Categorised, searchable emoji picker.
  - [ ] 7.3 **[Stretch]** Self-made notification sound, default muted, preference
        persisted.
  - [ ] 7.4 **[Stretch]** Tab-title badge and browser notification while hidden,
        permission requested on a user gesture only.
  - [ ] 7.5 **[Stretch]** Dark theme token set honouring `prefers-color-scheme`
        with a manual override.
  - _Verify:_ 7.1 by eye against the motion table. Each stretch item verified in
    isolation; none may regress tasks 1–6, and dropping any of them must leave the
    demo intact.
  - _Requirements: S1, S2, S3, S4_

---

## Sequencing notes

Tasks 1–3 need no server at all, so they can proceed in parallel with any backend
work. Task 4 is the first that requires `py -3 -m backend --serve`.

If time runs short, the honest cut line is after task 5: the app then demonstrates
the full conversation, product cards, handoff and resilience. Task 6's
accessibility pass should be preferred over task 7's stretch items if only one can
be done — a keyboard-inoperable demo is a worse outcome than a demo without
sounds.

## Definition of done for the slice set

- Tasks 1–5 complete, each verification step performed.
- No console errors or unhandled rejections in a full scenario run.
- Shared contract changes are covered by both backend and frontend tests.
- No sales intelligence visible anywhere in the customer UI.
- `docs/backend-contract.md` updated if any new gap was discovered.
- `docs/frontend-changelog.md` left untouched unless the owner has explicitly
  authorised an entry.
