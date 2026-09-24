# SalesPilot interface v2 — implementation delta

This document records additions made after the frozen `interface-v1.md`. All v1 fields retain their meanings. It does not claim real WhatsApp Cloud API transport or authentication.

## Customer conversation

`POST /api/messages` remains a text-message endpoint. A customer may reply to a handoff offer with `Confirm` / `Cancel` (also `yes` / `no`, with a small set of equivalent phrases). The browser buttons send these same words through the ordinary message endpoint; no button-only protocol is required. A pending handoff does **not** create a case or set `human_takeover`. A confirmed reply creates or reuses one active case and sets takeover; a cancelled reply creates none. The existing `client_message_id` receipt prevents retrying a confirmation from creating a second case.

Customer replies add nullable `customer_question`:

```json
{
  "field": "contact_reason",
  "prompt": "What would you like help with?",
  "options": [{"id": "1", "label": "Compare plans"}],
  "allow_other": true
}
```

The field and options come from the backend-approved catalog, never raw model output. The chat reply also contains a numbered text rendering. Customers can reply with an option number, option label or their own words. Selecting “Something else” asks for a free-text description. The browser renders a tappable list; a text-only channel works without it. `GET /api/conversations/{id}` now returns `quick_replies` and `customer_question` so a pending choice is restored after reload. Customer payloads still exclude score, priority, signals, case details, agent runs and diagnostics.

## Staff console

`POST /api/admin/opportunities/{opportunity_id}/brief` generates a staff-only handoff draft for a conversation with an active confirmed case. It returns `text`, `source` (`llm` or `template`), a bounded `evidence` object and model `usage` when available. It does not mutate the conversation or send text to the customer. The model request uses the existing per-run request, token, tool and cost limits; offline mode produces a clearly labelled template.

`GET /api/admin/dashboard` items add `attention_reason`. `GET /api/admin/cases` items add `priority`, `score` and `keywords`, copied from the linked backend opportunity rather than calculated by the browser. Opportunity detail adds `pending_handoff_reason`, `pending_question_field`, `collected_answers`, `evidence_sources` and `customer_question`. Score-history entries add `evidence`: backend rule version, input snapshot, per-dimension points/rules/message references and the fit/behaviour/priority calculations. Older stored history may have empty evidence; the UI says so rather than inventing provenance.

The admin `#/debug` route reuses existing model-run telemetry and score detail, then shows backend-authored score evidence and a bounded list of browser-observed API request/response bodies, status and duration. This is not a server-wide HTTP trace. The console has no authentication: run it only on localhost or a trusted private network. Credentials are not sent to the browser trace; public deployment requires access control.

## Representative availability

The fictional CareSure has no published real operating hours. `SALESPILOT_STAFF_HOURS_JSON` optionally supplies approved weekly windows in Singapore time, indexed `0` (Monday) through `6` (Sunday); `SALESPILOT_STAFF_CLOSED_DATES` supplies YYYY-MM-DD exceptions. The read-only `get_staff_availability` model tool reports whether the configured schedule is open and its next opening. The deterministic customer confirmation copy uses the same service. With no approved schedule it explicitly says verified hours are unavailable. Opening time is not a response-time estimate.

## Current limits

- Handoff confirmation recognises a deliberately small phrase set; ambiguous replies are treated as a new message, never implicit consent.
- The question catalog initially has `contact_reason`, `cover_type` and `followup_time`; the model can only propose a field, and backend rules decide whether to ask it.
- The staff brief is an on-demand draft, not an approved policy decision. Model-generated wording may need human verification.
- Browser-observed request history is session-local and bounded to 30 exchanges; it is not persisted server telemetry.
