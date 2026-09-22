# Requirements — Admin console UI

## Introduction

A staff console for CareSure sales representatives and operators, in
`frontend/admin/`. Three routes:

1. **Inbox** (landing) — pick a customer, read the conversation, see the sales
   intelligence and what the agent actually did, and reply as a human.
2. **Cases** — claim and resolve HITL escalations.
3. **Harness** — a test route that embeds the real customer app as a device, with
   debug controls and agent telemetry beside it.

Unlike the customer chat, this surface is **expected** to display everything:
opportunity state, score dimensions, priority, signals, next best action, and full
model observability — which operations ran, which tools were called, how many
model calls, tokens, time, cost, and the input and output content.

The first delivery is built entirely against a **mock transport** and does not
depend on the Python backend. The backend is mid-refactor; binding to it now would
invite rework. See `design.md` §Transport.

The legacy console in `salespilot/static/` is **frozen** and is not the baseline
for this work. One lesson carries over: its takeover button only toggles CSS and
never calls the API. This console performs real transitions.

Related: `docs/api/interface-v1.md` (contract, naming rules, visibility tiers,
topology) · `docs/backend-contract.md` (gap register) · `design.md` · `tasks.md` ·
`.kiro/steering/frontend-conventions.md` · customer design tokens in
`.kiro/specs/customer-chat-ui/ux-spec.md`.

**Vocabulary.** This document never says "turns" unqualified. Per
`interface-v1.md` §1.1 it uses `customer_message_count`, `agent_run_count`,
`agent_step_count`, `llm_call_count` and `tool_call_count`.

---

## Requirements

### Requirement 1: Conversation inbox and customer identity

**User story:** As a representative, I want one prioritised list of customers, so
that I can tell who needs me and pick them without ambiguity.

#### Acceptance criteria

1. WHEN the console loads THE SYSTEM SHALL display a list of all conversations in
   a left column, ordered by opportunity score descending, with null scores last.
2. WHEN a list row renders THE SYSTEM SHALL display the customer name, the
   opportunity id, the score, the priority, and a preview of the most recent
   message.
3. WHEN two customers share a display name THE SYSTEM SHALL remain unambiguous by
   showing the opportunity id on every row.
4. WHEN an avatar renders THE SYSTEM SHALL derive its initials from the customer
   name and its background colour deterministically from the opportunity id, so
   that identically named customers are visually distinct.
5. WHEN a conversation is under human takeover THE SYSTEM SHALL mark the row
   distinctly, using text or an icon and not colour alone.
6. WHEN a row is activated THE SYSTEM SHALL open that conversation in the
   workspace and indicate the row as selected.
7. WHEN the list is empty THE SYSTEM SHALL display an empty state offering to seed
   demo data.
8. WHEN the refresh control is activated THE SYSTEM SHALL reload the list without a
   full page reload.
9. WHEN the list renders THE SYSTEM SHALL NOT display an unread count, because no
   read state exists in the system; attention is conveyed by priority and takeover
   only.
10. WHEN identity is displayed anywhere THE SYSTEM SHALL treat `opportunity_id` as
    the key and `customer_name` as a label, and SHALL NOT assume the name is
    unique or mutable.

### Requirement 2: Conversation workspace and human reply

**User story:** As a representative, I want to read the conversation and answer
the customer myself.

#### Acceptance criteria

1. WHEN a conversation is open THE SYSTEM SHALL display the full transcript in
   chronological order with a timestamp on every message.
2. WHEN a message renders THE SYSTEM SHALL label its origin as the customer, the
   AI assistant, a human representative, or the system, deriving it from `role`
   and `author` per `interface-v1.md` §1.2.
3. WHEN `author` is absent from an agent-side message THE SYSTEM SHALL treat it as
   the AI assistant.
4. WHEN the transcript renders backend-supplied text THE SYSTEM SHALL render it as
   literal text and SHALL NOT interpret it as markup.
5. WHEN the opportunity is under human takeover THE SYSTEM SHALL enable the reply
   composer.
6. WHEN the opportunity is not under human takeover THE SYSTEM SHALL disable the
   reply composer and SHALL state that a takeover is required first.
7. WHEN the transport cannot deliver a human reply THE SYSTEM SHALL disable the
   composer and SHALL state that the backend does not yet support it, rather than
   failing on submit.
8. WHEN a human reply is submitted THE SYSTEM SHALL append it attributed to the
   representative, and SHALL NOT display it as AI output.
9. WHEN a human reply fails THE SYSTEM SHALL keep the drafted text and surface a
   non-blocking error.
10. WHEN a reply is sent THE SYSTEM SHALL identify the operator from configuration,
    since the system has no authentication.

### Requirement 3: Sales intelligence panel

**User story:** As a representative, I want the opportunity assessment beside the
conversation.

#### Acceptance criteria

1. WHEN a conversation is open THE SYSTEM SHALL display state, product, priority,
   total score, main concern, competitive risk, churn risk, compliance risk,
   expansion flags, takeover status, and `customer_message_count`.
2. WHEN the five score dimensions are available THE SYSTEM SHALL display each with
   its value and maximum; WHEN they are unavailable THE SYSTEM SHALL display the
   total alone rather than inventing a breakdown.
3. WHEN score history exists THE SYSTEM SHALL display each entry with timestamp,
   score, state and trigger.
4. WHEN state history exists THE SYSTEM SHALL display each transition with
   timestamp, source state, target state and the backend's reason.
5. WHEN a next best action exists THE SYSTEM SHALL display its action, reason and
   whether human intervention is required.
6. WHEN the opportunity is under takeover THE SYSTEM SHALL surface the linked open
   case's reason and recommended action.
7. WHEN the console displays any state, score, priority, signal or next best
   action THE SYSTEM SHALL use the backend value verbatim and SHALL NOT recompute,
   re-band or re-rank it.
8. WHEN priority counts are shown THE SYSTEM SHALL tally the backend's priority
   values and SHALL NOT derive bands from raw scores.

### Requirement 4: Agent observability

**User story:** As an operator, I want to see exactly what the agent did for each
exchange, including what it cost.

#### Acceptance criteria

1. WHEN agent run data is available for a conversation THE SYSTEM SHALL list one
   entry per run, newest last, showing the trigger, start time, duration and
   status.
2. WHEN a run entry is selected THE SYSTEM SHALL display its ordered steps, each
   with name, kind, duration and status.
3. WHEN a run includes model calls THE SYSTEM SHALL display per call the purpose,
   model name, duration, prompt tokens, completion tokens, total tokens and cost.
4. WHEN a model call reports input or output content THE SYSTEM SHALL display the
   content and its character length.
5. WHEN content is withheld by the backend THE SYSTEM SHALL display the character
   length alone and SHALL indicate that content is not exposed.
6. WHEN a run reports totals THE SYSTEM SHALL display `agent_step_count`,
   `llm_call_count`, `tool_call_count`, total tokens and total cost.
7. WHEN a conversation is open THE SYSTEM SHALL display a running total of tokens
   and cost across its runs.
8. WHEN `tool_call_count` is zero THE SYSTEM SHALL display zero and SHALL NOT
   present retrieval steps as tool calls.
9. WHEN a run status is `degraded` THE SYSTEM SHALL display it distinctly from
   `ok` and identify the step that degraded.
10. WHEN the backend does not report telemetry THE SYSTEM SHALL display
    client-observed duration and status only, and SHALL label the remaining
    metrics as not reported rather than showing zeros.
11. WHEN a cost is displayed THE SYSTEM SHALL render the backend's amount and
    currency and SHALL NOT compute cost from tokens locally.

### Requirement 5: Cases

**User story:** As a representative, I want to claim and resolve escalations so
that ownership is unambiguous.

#### Acceptance criteria

1. WHEN the cases route loads THE SYSTEM SHALL list all cases with open ones
   reachable first.
2. WHEN a case renders THE SYSTEM SHALL display its id, customer name, opportunity
   state, product, escalation reason, summary, recommended action, status and
   creation time.
3. WHEN comparing a case status THE SYSTEM SHALL normalise the backend's title
   case values `Open`, `Taken Over` and `Closed` before matching.
4. WHEN a case is open THE SYSTEM SHALL offer take-over and resolve controls; WHEN
   taken over, resolve only; WHEN closed, neither.
5. WHEN a transition is requested THE SYSTEM SHALL send a real request and SHALL
   NOT change the display until a successful response, updating from the response
   body rather than the requested value.
6. WHEN a transition is in flight THE SYSTEM SHALL disable that case's controls.
7. WHEN a transition fails THE SYSTEM SHALL leave the case unchanged and display a
   non-blocking inline error.
8. WHEN a transition succeeds THE SYSTEM SHALL refresh the case and the open-case
   count in the navigation.
9. WHEN resolve is offered THE SYSTEM SHALL state that closing a case clears human
   takeover and allows the AI to resume autonomous selling on the customer's next
   message.
10. WHEN a case is taken over from the workspace THE SYSTEM SHALL enable that
    conversation's reply composer without a page reload.

### Requirement 6: Test harness

**User story:** As an operator, I want to drive a real customer device from inside
the console and watch what the agent does.

#### Acceptance criteria

1. WHEN the harness route opens THE SYSTEM SHALL embed the unmodified customer app
   in an iframe on the right, framed as a device.
2. WHEN the harness renders THE SYSTEM SHALL place debug information and controls
   on the left.
3. WHEN the harness embeds the device THE SYSTEM SHALL NOT reimplement any part of
   the customer chat UI.
4. WHEN the device reports an exchange THE SYSTEM SHALL record a timeline entry
   with the correlation id, client-observed duration and status.
5. WHEN a timeline entry is selected THE SYSTEM SHALL display the agent run
   telemetry for that correlation id, subject to Requirement 4.
6. WHEN the operator changes the simulated customer identity, transport or
   scenario THE SYSTEM SHALL apply it to the device without a console reload.
7. WHEN the operator resets the device THE SYSTEM SHALL clear the conversation and
   the timeline.
8. WHEN the operator injects a message THE SYSTEM SHALL cause the device to send it
   as if the customer had typed it.
9. WHEN the console and the device exchange messages THE SYSTEM SHALL use an
   explicit target origin and SHALL validate the origin of every received message.
10. WHEN the device is not embedded THE SYSTEM SHALL cause the customer app to emit
    no telemetry at all.
11. WHEN telemetry is routed THE SYSTEM SHALL obtain sensitive agent data from the
    backend admin surface and SHALL NOT route it through the customer app, because
    the customer surface has no shape for it.
12. WHEN sales intelligence is displayed in the harness THE SYSTEM SHALL display it
    only in the left panel and never inside the device.

### Requirement 7: Navigation and layout

#### Acceptance criteria

1. WHEN the console loads THE SYSTEM SHALL present exactly three destinations and
   SHALL land on Inbox.
2. WHEN a destination is active THE SYSTEM SHALL indicate it in the navigation.
3. WHEN open cases exist THE SYSTEM SHALL display their count as a badge in the
   navigation.
4. WHEN the viewport is at least 1200 pixels wide THE SYSTEM SHALL show the inbox
   list, the conversation and the side panel simultaneously.
5. WHEN the viewport is narrower than 1200 pixels THE SYSTEM SHALL collapse the
   side panel into a tabbed region rather than overlapping content.
6. WHEN the viewport is narrower than 900 pixels THE SYSTEM SHALL place navigation
   above the content.
7. WHEN a route is selected THE SYSTEM SHALL reflect it in the URL fragment so the
   view survives a reload.

### Requirement 8: Transport and data integrity

#### Acceptance criteria

1. WHEN the console boots THE SYSTEM SHALL select one transport from
   configuration, from `mock` or `salespilot`.
2. WHEN `mock` is selected THE SYSTEM SHALL operate the entire console with no
   network access.
3. WHEN a view needs data THE SYSTEM SHALL obtain it from the store, and the view
   SHALL NOT perform network requests directly.
4. WHEN a request fails THE SYSTEM SHALL display an error state for the affected
   region and SHALL NOT present stale data as current.
5. WHEN an optional field is absent THE SYSTEM SHALL display a neutral placeholder.
6. WHEN a capability defined in `docs/backend-contract.md` is unavailable THE
   SYSTEM SHALL disable the dependent control with a stated reason and SHALL remain
   usable.

### Requirement 9: Configuration, states and accessibility

#### Acceptance criteria

1. WHEN the console boots THE SYSTEM SHALL read the API base, transport, operator
   name, refresh interval and feature flags from one configuration module.
2. WHEN a user-facing string is displayed THE SYSTEM SHALL source it from the
   strings module.
3. WHEN a region is loading THE SYSTEM SHALL display a loading state distinct from
   its empty state.
4. WHEN a region has no data THE SYSTEM SHALL explain how to populate it.
5. WHEN an interactive control renders THE SYSTEM SHALL give it an accessible name
   and a visible focus indicator.
6. WHEN tabular data renders THE SYSTEM SHALL use table semantics with header cells
   associated to columns.
7. WHEN status is conveyed THE SYSTEM SHALL pair colour with text or an icon.
8. WHEN the operator navigates by keyboard alone THE SYSTEM SHALL make navigation,
   inbox rows, case controls, the composer and the timeline reachable and operable.

> Accessibility here is a baseline, not a conformance claim. Full WCAG validation
> would require manual assistive-technology testing and expert review.

---

## Stretch

- **[Stretch] A1 — Analytics view** from `GET /api/analytics`.
- **[Stretch] A2 — Auto-refresh** with a visible last-updated time and a pause
  control.
- **[Stretch] A3 — Scenario scripting** in the harness: replay a scripted
  conversation turn by turn.
- **[Stretch] A4 — Dark theme.**
- **[Stretch] A5 — Cost budget alert** when a conversation exceeds a configured
  spend.

## Excluded

- **[Out]** Authentication, operator accounts, per-rep assignment. Any visitor can
  take over any case. Accepted demo limitation; do not add a fake login.
- **[Out]** Search, filtering, sort controls, pagination, bulk actions.
- **[Out]** Editing opportunities, scores or states by hand. The console is
  read-only except for case transitions and human replies.
- **[Out]** Export.
- **[Out]** Any modification to the legacy console or the Python backend.
- **[Out]** A browser-local channel between independently opened frontends, per
  `interface-v1.md` §3.
