---
inclusion: always
---

# SalesPilot — product context

SalesPilot is an AI sales assistant for **CareSure Health Insurance** (a fictional
insurer used for demo purposes). It turns customer conversations into structured
sales opportunities: every message is analysed for sales signals, the customer's
position in the buying journey is tracked, the opportunity is scored, a priority
and next best action are derived, and the case is escalated to a human sales
representative when required.

The business name is fixed as **CareSure**. Do not introduce alternative branding.

## Two audiences, two frontends

| Audience | Surface | Location |
| --- | --- | --- |
| End customer | WhatsApp-style chat app. Sees only the conversation. | `frontend/customer/` |
| Sales staff | Trimmed admin console: opportunity queue, case takeover, customer detail. | `frontend/admin/` |

These are **independent** from the pre-existing console in `salespilot/static/`.
That legacy console stays untouched and is not to be extended or refactored.

Customers must never see internal sales intelligence (opportunity score,
priority, detected signals, state names, next best action). That data belongs to
the admin surface only.

## Non-goals

- No authentication, authorisation, or multi-tenancy. The demo is single-user and
  trusted. Treat this as a known limitation, not something to silently fix.
- No real WhatsApp messaging. The WhatsApp transport is a shape-only stub.
- No voice notes, no image upload, no message reactions.
- No internationalisation. The product is English-only; user-facing strings live
  in one module so translation stays possible later.
- No rewrite of the legacy console, and no changes to the Python backend from
  frontend work (see `tech.md`).

## Compliance red lines

These mirror constraints already enforced in the backend and must be preserved by
any frontend that renders backend output:

- The assistant is **labelled as AI** in the UI. Never present it as a human.
- Premium figures are fictional indicative rates. When a reply contains premium
  information, the demo disclaimer returned by the backend must remain visible;
  never truncate or hide it.
- The frontend performs **no business logic**. State, signals, score, priority,
  next best action and escalation decisions are computed by the backend and only
  displayed. Do not re-derive or guess them client-side.
- Do not use WhatsApp trademarks: no WhatsApp logo, no WhatsApp Sans font, no
  WhatsApp notification sound. "WhatsApp-style" means layout and interaction
  conventions only.

## Documentation rule — frontend changelog is gated

`docs/frontend-changelog.md` records what changed in each frontend update.

**Do not create, edit, or append to that file unless the user explicitly asks for
it in the current turn.** A completed code change is not authorisation. If a
change seems worth recording, finish the work and mention that the changelog
entry is pending the user's go-ahead.
