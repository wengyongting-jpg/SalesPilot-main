# Requirements — Admin console UI

## Introduction

A trimmed staff console for CareSure sales representatives, living in
`frontend/admin/`. It answers three questions and nothing more:

1. Who needs attention right now, and why? — the **queue**
2. What should I do about this escalation? — **case takeover**
3. What is this customer's full story? — **customer detail**

Deliberately narrow. This is a supporting surface, not the product's core
innovation. Anything beyond those three questions is out of scope for the first
delivery, including analytics charts, search, filtering, bulk actions, and
representative accounts.

The legacy console in `salespilot/static/` already covers similar ground. It is
**frozen** and not the baseline for this work: it is not being extended, migrated,
or refactored. This is a fresh, smaller app. One concrete lesson is carried over
though — the legacy chat panel's takeover button only toggles CSS and never calls
the API. This console must perform real state transitions.

Related documents:

- API reference and outstanding backend gaps: `docs/backend-contract.md`
- Architecture: `design.md`
- Slices and verification: `tasks.md`
- Shared conventions: `.kiro/steering/frontend-conventions.md`
- Design tokens to align with: `.kiro/specs/customer-chat-ui/ux-spec.md`

Unlike the customer chat, this surface is **expected** to display sales
intelligence in full: score, priority, signals, state, and next best action.

---

## Requirements

### Requirement 1: Opportunity queue

**User story:** As a sales representative, I want a single prioritised list of
opportunities, so that I know who to contact first.

#### Acceptance criteria

1. WHEN the console loads THE SYSTEM SHALL retrieve all opportunities and display
   them in one list.
2. WHEN the queue renders THE SYSTEM SHALL order rows by opportunity score
   descending, so the highest-value opportunity appears first.
3. WHEN a queue row renders THE SYSTEM SHALL display customer name, opportunity
   state, score out of 100, priority, active signals, and the next action.
4. WHEN a priority is displayed THE SYSTEM SHALL use a distinct visual treatment
   per band, for HIGH, MEDIUM and LOW.
5. WHEN an opportunity is under human takeover THE SYSTEM SHALL mark the row
   visibly as requiring or receiving human handling.
6. WHEN the queue renders THE SYSTEM SHALL display counts of opportunities per
   priority band above the list.
7. WHEN no opportunities exist THE SYSTEM SHALL display an empty state offering to
   seed demo data.
8. WHEN the seed control is activated THE SYSTEM SHALL request demo seeding and
   refresh the queue.
9. WHEN the refresh control is activated THE SYSTEM SHALL reload queue data
   without a full page reload.
10. WHEN a queue row is activated THE SYSTEM SHALL open the customer detail view
    for that opportunity.

### Requirement 2: Case takeover

**User story:** As a sales representative, I want to claim and resolve escalated
cases, so that ownership is unambiguous.

#### Acceptance criteria

1. WHEN the cases view loads THE SYSTEM SHALL retrieve all HITL cases and display
   them grouped or sorted so open cases are reachable first.
2. WHEN a case renders THE SYSTEM SHALL display its id, customer name,
   opportunity state, product, escalation reason, summary, recommended action,
   status, and creation time.
3. WHEN a case status is compared THE SYSTEM SHALL normalise the backend's
   title-case values, being `Open`, `Taken Over` and `Closed`, before matching.
4. WHEN a case is open THE SYSTEM SHALL offer a take-over control and a resolve
   control.
5. WHEN a case is taken over THE SYSTEM SHALL offer only a resolve control.
6. WHEN a case is closed THE SYSTEM SHALL offer no state-changing control.
7. WHEN the take-over control is activated THE SYSTEM SHALL send a real status
   transition request to the backend and SHALL NOT change the display without a
   successful response.
8. WHEN a status transition succeeds THE SYSTEM SHALL refresh the affected case
   and the open-case count.
9. WHEN a status transition fails THE SYSTEM SHALL leave the case unchanged and
   display a non-blocking error.
10. WHEN a case is resolved THE SYSTEM SHALL make clear in the interface that
    closing a case clears human takeover on the opportunity and allows the AI to
    resume autonomous selling on the customer's next message.
11. WHEN open cases exist THE SYSTEM SHALL display a badge with the open-case
    count in the navigation.

> Criterion 10 matters because the backend's `PATCH /api/cases/{id}` to `CLOSED`
> has exactly that side effect. A representative who closes a case without knowing
> this would unknowingly hand the conversation back to the AI.

### Requirement 3: Customer detail

**User story:** As a sales representative, I want one customer's full history, so
that I can pick up the conversation with context.

#### Acceptance criteria

1. WHEN the detail view opens for an opportunity THE SYSTEM SHALL display customer
   name, state, product, score with its five dimensions, priority, main concern,
   competitive risk, churn risk, compliance risk, expansion flags, takeover
   status, and turn count.
2. WHEN score history exists THE SYSTEM SHALL display it in chronological order
   with the timestamp, score, state, and trigger for each entry.
3. WHEN state history exists THE SYSTEM SHALL display each transition with
   timestamp, source state, target state, and the reason recorded by the backend.
4. WHEN the conversation transcript is displayed THE SYSTEM SHALL show each
   message with its timestamp and an explicit author label distinguishing customer
   from assistant.
5. WHEN the detail view renders any backend-supplied text THE SYSTEM SHALL render
   it as literal text and SHALL NOT interpret it as markup.
6. WHEN the opportunity has no score yet THE SYSTEM SHALL display a neutral
   placeholder rather than a zero or an error.
7. WHEN the requested opportunity does not exist THE SYSTEM SHALL display a
   not-found state rather than an empty view.
8. WHEN a detail view is open AND the underlying opportunity is under takeover THE
   SYSTEM SHALL surface the linked case's reason and recommended action.

### Requirement 4: Navigation and layout

**User story:** As a representative, I want to move between the three views
without losing context.

#### Acceptance criteria

1. WHEN the console loads THE SYSTEM SHALL present exactly three destinations:
   queue, cases, and customer detail.
2. WHEN a destination is active THE SYSTEM SHALL indicate it in the navigation.
3. WHEN the viewport is at least 900 pixels wide THE SYSTEM SHALL present
   navigation alongside the content area.
4. WHEN the viewport is narrower than 900 pixels THE SYSTEM SHALL collapse
   navigation above the content rather than overlapping it.
5. WHEN the customer detail view is opened from a queue row THE SYSTEM SHALL allow
   returning to the queue.

### Requirement 5: Data access and integrity

**User story:** As a developer, I want the console to display backend truth only.

#### Acceptance criteria

1. WHEN the console displays state, score, priority, signals, next best action, or
   escalation reason THE SYSTEM SHALL use the backend's values verbatim and SHALL
   NOT recompute, re-band, or re-rank them by its own rules.
2. WHEN the console derives the priority counts for Requirement 1.6 THE SYSTEM
   SHALL count the backend-supplied priority values and SHALL NOT recalculate
   bands from raw scores.
3. WHEN a backend request fails THE SYSTEM SHALL display an error state for the
   affected view and SHALL NOT silently render stale data as current.
4. WHEN an expected optional field is absent THE SYSTEM SHALL display a neutral
   placeholder.
5. WHEN a view module needs data THE SYSTEM SHALL obtain it from the store, and
   the view SHALL NOT perform network requests directly.

### Requirement 6: Configuration, states, and accessibility

**User story:** As the demo operator and as a keyboard user, I want the console
configurable and operable.

#### Acceptance criteria

1. WHEN the console boots THE SYSTEM SHALL read the API base, refresh interval,
   and feature flags from a single configuration module.
2. WHEN a user-facing string is displayed THE SYSTEM SHALL source it from the
   strings module.
3. WHEN a view is loading THE SYSTEM SHALL display a loading state distinct from
   its empty state.
4. WHEN a view has no data THE SYSTEM SHALL display an empty state explaining how
   to populate it.
5. WHEN any interactive control renders THE SYSTEM SHALL give it an accessible
   name and a visible focus indicator.
6. WHEN tabular data renders THE SYSTEM SHALL use table semantics with header
   cells associated to their columns.
7. WHEN the representative navigates by keyboard alone THE SYSTEM SHALL make
   navigation, queue rows, case controls, and refresh controls reachable and
   operable.
8. WHEN status is conveyed THE SYSTEM SHALL NOT rely on colour alone, and SHALL
   pair it with text or an icon.

> Accessibility here is a baseline, not a conformance claim. Full WCAG validation
> would require manual assistive-technology testing and expert review.

---

## Stretch requirements

Not part of the first delivery.

- **[Stretch] A1 — Analytics view.** Funnel, priority mix, signal frequency and
  conversion rate from `GET /api/analytics`.
- **[Stretch] A2 — Auto-refresh.** Periodic queue polling with a visible
  last-updated time and a pause control.
- **[Stretch] A3 — Representative reply.** A composer in the case view, enabled
  only once the backend provides a rep-reply endpoint.
- **[Stretch] A4 — Dark theme.**

## Excluded

- **[Out]** Authentication, representative identity, and per-rep assignment. Any
  visitor can take over any case; recorded in `docs/backend-contract.md`.
- **[Out]** Search, filtering, sorting controls, pagination, and bulk actions.
- **[Out]** Editing opportunities, scores, or states by hand. The console is
  read-only except for case status transitions.
- **[Out]** Exporting data.
- **[Out]** Any modification to the legacy console or the Python backend.
