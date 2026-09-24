# Backend/frontend handoff

This is the current integration note for the two maintained applications. The
historical rebuild rationale remains in `backend-plan.md`; the live code is under
`backend/` and `frontend/`.

## Ownership and boundaries

| Area | Responsibility |
| --- | --- |
| `backend/**`, `backend/tests/**` | Business rules, model orchestration, storage, HTTP schemas and visibility tiers |
| `frontend/customer/**` | Customer-safe conversation UI; never receives sales intelligence |
| `frontend/admin/**` | Staff queue, cases, human replies and agent-run diagnostics |
| `data/**` | Approved product knowledge and local SQLite data |
| `evals/**` | Multi-turn behaviour cases and evaluation tooling |
| `docs/v0.0/api/interface-v1.md` | Shared wire contract |

The provider API is private to the backend. Browsers never receive or call an LLM
key; they call the SalesPilot REST API only.

## Live integration

Customer endpoints:

- `POST /api/messages`
- `GET /api/conversations/{id}?since=<message-id-or-timestamp>`
- `DELETE /api/conversations/{id}`

Admin endpoints are namespaced under `/api/admin/*` and include the dashboard,
opportunity detail, case transitions, representative replies, analytics and agent
runs. The dashboard is deliberately lightweight: each queue row carries at most
the latest message and no score/state histories; detail is fetched when a row opens.

Human replies use `role: "business"`, `author: "human"`,
`generation: "human"` and may include customer-safe `rep_name`. The customer app
polls incrementally only while `human_takeover` is true, then stops immediately
when takeover ends.

## Capability status

| Capability | Status |
| --- | --- |
| Customer/server idempotency | Implemented with `client_message_id` |
| Quick replies | Implemented; maximum three; suppressed under takeover |
| Incremental transcript fetch | Implemented with message-id or ISO timestamp cursor |
| Representative reply | Implemented and persisted |
| Agent-run telemetry | Implemented, including calls, tools, tokens and cost |
| Health/CORS | Implemented for the local 8123 → 8000 setup |
| WhatsApp Cloud API transport | Not implemented; the adapter is an explicit stub |
| Authentication/multi-tenancy | Out of demo scope |

## Verification

```powershell
py -3 -m unittest discover -s backend/tests
node --test "frontend/tests/**/*.test.js"
```

Current baseline: 428 backend tests and 283 frontend tests.

For a manual end-to-end check, run `py -3 -m backend --serve --seed`, serve the
`frontend/` directory on port 8123, open the Inbox, take over a case and send a
representative reply. The customer view for that conversation should receive the
message within the configured two-second polling interval and show the rep name.
