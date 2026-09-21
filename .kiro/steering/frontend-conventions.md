---
inclusion: fileMatch
fileMatchPattern: ["frontend/**/*.html", "frontend/**/*.css", "frontend/**/*.js"]
---

# Frontend conventions

Applies to everything under `frontend/`. Backend files stay read-only; see
`tech.md`.

## File layout per app

Each app is self-contained and runnable by opening `index.html`:

```
frontend/<app>/
├── index.html
├── css/
│   ├── tokens.css        # design tokens only — no component rules
│   └── app.css           # component rules, consuming tokens
└── js/
    ├── main.js           # entry: wire store -> views, boot
    ├── config.js         # branding, endpoints, feature flags, timings
    ├── strings.js        # every user-facing string (English)
    ├── store.js          # conversation/queue state + subscribe()
    ├── gateway/
    │   ├── index.js      # selects an adapter from config
    │   ├── salespilot.js # our FastAPI backend
    │   ├── whatsapp.js   # WhatsApp Cloud API — shape-only stub
    │   └── mock.js       # scripted, no server required
    └── views/            # one module per component, DOM-only
```

## Hard rules

1. **No business logic.** Never compute or infer state, signals, score, priority,
   next best action, or escalation client-side. Render what the backend returns.
   If a field is missing, degrade visibly-neutral (hide the element) rather than
   guessing a value.
2. **No hardcoded strings in views.** All user-facing text comes from
   `strings.js`. All colours, spacing, radii, durations come from `tokens.css`.
3. **No inline event handlers.** Do not use `onclick="..."` in HTML. Attach
   listeners in JS with `addEventListener`. (The legacy console uses inline
   handlers; do not copy that pattern.)
4. **Escape all untrusted text.** Message bodies, customer names, case summaries
   and knowledge-base facts are rendered as text, never as HTML. Prefer
   `element.textContent`. If you must build markup, escape first.
5. **Views never call `fetch`.** Only gateway adapters perform network I/O. Views
   read from the store and dispatch intents.
6. **No dependencies.** No npm, no CDN, no build step.

## Design tokens

Define tokens as CSS custom properties on `:root` in `tokens.css`. Component CSS
must reference `var(--token)` and never literal colours or pixel values for
anything token-worthy. Both apps keep separate token files but should agree on
the shared scale (spacing, radii, durations) so they feel like one product.
Concrete values for the customer app live in
`.kiro/specs/customer-chat-ui/ux-spec.md`.

## Branding and trademark red lines

The chat is *WhatsApp-style*, not a WhatsApp clone:

- Do not ship the WhatsApp logo, wordmark, or any Meta brand asset.
- Do not use WhatsApp Sans / WhatsApp Sans Var. Use a system font stack.
- Do not reuse WhatsApp's notification sound. Any sound must be self-made.
- Do not imply affiliation with WhatsApp or Meta anywhere in the UI or docs.
- The assistant must be visibly labelled as AI in the chat header.

Visual conventions (bubble geometry, tick semantics, grouping, date separators)
are generic messaging patterns and are fine to follow. Where CSS values were
derived from public open-source recreations, credit the source in a comment.

## Adapter rules

- All adapters normalise to one internal message shape:
  `{ id, clientId, direction: 'out'|'in', text, ts, status, blocks[] }`.
- `salespilot.js` must work against **today's** API and tolerate the **target**
  API from `docs/backend-contract.md`. Treat every field added by the contract as
  optional: absent `quick_replies` means no chips, absent message `id` means fall
  back to `clientId`.
- Never let a missing backend capability block a frontend task. Degrade, and note
  the gap in `docs/backend-contract.md`.
- `whatsapp.js` stays a stub: document the Cloud API payload shape and the field
  mapping in comments, throw a clear "not implemented" error on send.
- Every send carries a client-generated `clientId`. Retries reuse it so the
  backend can deduplicate once idempotency lands.

## Accessibility baseline

Not a full audit, but these are non-negotiable: every control has an accessible
name, focus is visible, the message list is a labelled live region, contrast
meets WCAG AA for text, and the composer is fully keyboard operable. Full WCAG
conformance would require manual assistive-technology testing and expert review;
this baseline does not claim it.

## Changelog

`docs/frontend-changelog.md` is updated **only when the user explicitly asks**.
Finishing a change does not authorise an entry.
