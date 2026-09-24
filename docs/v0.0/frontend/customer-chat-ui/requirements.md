# Requirements — Customer chat UI

## Introduction

A WhatsApp-style chat application for CareSure customers, living in
`frontend/customer/`. It is the customer-facing half of SalesPilot: the customer
types messages, the AI assistant replies, and a human representative can take
over. The app shows **only** the conversation. All sales intelligence (score,
priority, signals, state, next best action) stays in the admin console.

Scope is deliberately trimmed for an agile, demo-focused build. This is a
supporting surface, not the product's core innovation. Requirements marked
**[Stretch]** are explicitly out of the first delivery and must not block it.
Requirements marked **[Out]** are excluded.

Related documents:

- API reference and outstanding backend gaps: `docs/v0.0/backend/backend-contract.md`
- Visual and motion specification: `ux-spec.md`
- Architecture: `design.md`
- Slices and verification: `tasks.md`

Vocabulary: **outgoing** means sent by the customer; **incoming** means received
from the AI assistant or a human representative.

---

## Requirements

### Requirement 1: Conversation rendering

**User story:** As a customer, I want the conversation to read like a familiar
messaging app, so that I can follow it without effort.

#### Acceptance criteria

1. WHEN the message list renders THE SYSTEM SHALL display outgoing messages
   right-aligned and incoming messages left-aligned, each in a rounded bubble.
2. WHEN a message is the first of a run from the same sender THE SYSTEM SHALL
   render a bubble tail on that message only, and omit the tail on subsequent
   messages in the run.
3. WHEN consecutive messages come from the same sender within 60 seconds THE
   SYSTEM SHALL group them with reduced vertical spacing.
4. WHEN two adjacent messages fall on different calendar dates THE SYSTEM SHALL
   insert a centred date separator between them.
5. WHEN a message's date is today or yesterday THE SYSTEM SHALL label the
   separator "Today" or "Yesterday" respectively, otherwise an absolute date.
6. WHEN any message is rendered THE SYSTEM SHALL display its local time in
   24-hour `HH:MM` form inside the bubble.
7. WHEN message text contains characters that are significant in HTML THE SYSTEM
   SHALL render them as literal text and SHALL NOT interpret them as markup.
8. WHEN a message body consists only of emoji, up to three THE SYSTEM SHALL
   render them at enlarged size with no bubble background.
9. WHEN incoming text contains a URL THE SYSTEM SHALL render it as plain text
   without creating a hyperlink.

### Requirement 2: Sending and delivery status

**User story:** As a customer, I want to see whether my message got through, so
that I know when to retry.

#### Acceptance criteria

1. WHEN the composer is empty THE SYSTEM SHALL disable the send control and
   SHALL display a microphone glyph in its place.
2. WHEN the composer contains at least one non-whitespace character THE SYSTEM
   SHALL enable the send control and SHALL display a send glyph.
3. WHEN the customer submits a message THE SYSTEM SHALL append it to the list
   immediately, clear the composer, and mark the message `sending`.
4. WHEN a message is `sending` THE SYSTEM SHALL display a clock indicator on it.
5. WHEN the request returns a 2xx response THE SYSTEM SHALL mark the message
   `sent` and display a single tick.
6. WHEN the assistant's reply for that message has been rendered THE SYSTEM SHALL
   mark the outgoing message `read` and display a double tick in the accent
   colour.
7. WHEN the request fails or times out THE SYSTEM SHALL mark the message `failed`
   and display an error indicator with an accessible retry control.
8. WHEN the customer activates retry on a failed message THE SYSTEM SHALL resend
   it reusing the original `clientId` and SHALL NOT create a second bubble.
9. WHEN a send is in flight THE SYSTEM SHALL keep the composer editable so the
   customer can continue typing.
10. WHEN the backend has not advertised idempotency support THE SYSTEM SHALL
    still render the retry control but SHALL warn, via its accessible
    description, that retrying may duplicate the message.

> The tick mapping above is intentionally anchored to real client-observable
> events rather than simulated timers. The backend exposes no delivery receipts;
> see `docs/v0.0/backend/backend-contract.md` Part B item 5.

### Requirement 3: Assistant response and typing indicator

**User story:** As a customer, I want to know the assistant is working on my
message, so that the wait does not feel broken.

#### Acceptance criteria

1. WHEN a send request is in flight THE SYSTEM SHALL display a typing indicator
   in the incoming position with animated dots.
2. WHEN a send request is in flight THE SYSTEM SHALL display a typing status in
   the header.
3. WHEN the reply arrives or the request fails THE SYSTEM SHALL remove the typing
   indicator.
4. WHEN a reply arrives THE SYSTEM SHALL render it as an incoming message and
   SHALL NOT display any score, priority, signal, opportunity state, or next best
   action anywhere in the customer UI.
5. WHEN a reply contains premium figures together with the backend's demo
   disclaimer THE SYSTEM SHALL render the disclaimer in full and SHALL NOT
   truncate, collapse, or hide it.
6. WHEN the assistant is displayed in the header THE SYSTEM SHALL label it
   explicitly as an AI assistant.

### Requirement 4: Scrolling and unread tracking

**User story:** As a customer, I want the newest message in view without losing
my place when I scroll back.

#### Acceptance criteria

1. WHEN a new message arrives AND the list is scrolled to within 80 pixels of the
   bottom THE SYSTEM SHALL scroll smoothly to the newest message.
2. WHEN a new incoming message arrives AND the list is scrolled further than 80
   pixels from the bottom THE SYSTEM SHALL NOT move the scroll position and SHALL
   display a jump-to-latest control.
3. WHEN the jump-to-latest control is visible THE SYSTEM SHALL show the count of
   incoming messages received since the customer last reached the bottom.
4. WHEN the jump-to-latest control is activated THE SYSTEM SHALL scroll to the
   newest message and reset the count to zero.
5. WHEN the customer sends a message THE SYSTEM SHALL always scroll to the bottom
   regardless of prior scroll position.

### Requirement 5: Quick replies

**User story:** As a customer, I want suggested replies, so that I can move
forward without typing.

#### Acceptance criteria

1. WHEN a response includes a non-empty `quick_replies` array THE SYSTEM SHALL
   render each item as a tappable chip below the latest incoming message.
2. WHEN a chip is activated THE SYSTEM SHALL send its label as an outgoing
   message following the normal send flow, and SHALL remove the chip row.
3. WHEN the customer types in the composer THE SYSTEM SHALL hide the chip row.
4. WHEN a response omits `quick_replies` or returns an empty array THE SYSTEM
   SHALL render no chips and SHALL NOT invent suggestions locally.
5. WHEN more than three chips are returned THE SYSTEM SHALL render only the first
   three.

> The backend does not yet return `quick_replies`. Until it does, criterion 4
> governs and the feature is invisible. See `docs/v0.0/backend/backend-contract.md` Part B
> item 2.

### Requirement 6: Rich content blocks

**User story:** As a customer, I want plan information presented clearly rather
than as a wall of text.

#### Acceptance criteria

1. WHEN a response identifies a specific product AND carries retrieved knowledge
   facts THE SYSTEM SHALL render a product card showing the plan name and up to
   four facts.
2. WHEN a product card renders THE SYSTEM SHALL source every fact verbatim from
   the backend's retrieval output and SHALL NOT paraphrase, reorder for emphasis,
   or add facts of its own.
3. WHEN a product card's facts include premium information THE SYSTEM SHALL
   display the demo disclaimer within or directly beneath the card.
4. WHEN a response identifies no specific product THE SYSTEM SHALL render the
   reply as a plain text bubble.
5. WHEN the conversation contains a lifecycle event such as human takeover
   beginning THE SYSTEM SHALL render a centred system message distinct from
   customer and assistant bubbles.

### Requirement 7: Human handoff

**User story:** As a customer, I want to know when a real person has taken over,
so that I understand who I am talking to.

#### Acceptance criteria

1. WHEN a response reports that human takeover has become active THE SYSTEM SHALL
   render a system message stating that a representative is now handling the
   conversation.
2. WHEN human takeover is active THE SYSTEM SHALL display a persistent banner
   below the header.
3. WHEN human takeover is active THE SYSTEM SHALL update the header to indicate a
   human representative rather than the AI assistant.
4. WHEN human takeover is active THE SYSTEM SHALL render no quick-reply chips.
5. WHEN human takeover ends THE SYSTEM SHALL remove the banner and restore the AI
   assistant label.
6. WHEN human takeover is active THE SYSTEM SHALL keep the composer enabled so
   the customer can continue writing.

### Requirement 8: Connectivity and resilience

**User story:** As a customer, I want the app to behave predictably when the
network is unreliable.

#### Acceptance criteria

1. WHEN the backend health check fails THE SYSTEM SHALL display an offline banner
   describing the state in customer-appropriate language.
2. WHEN connectivity is restored THE SYSTEM SHALL remove the offline banner
   without requiring a page reload.
3. WHEN the browser reports going offline THE SYSTEM SHALL display the offline
   banner immediately without waiting for a failed request.
4. WHEN a reconnection occurs AND messages are in `failed` state THE SYSTEM SHALL
   leave them failed and await explicit retry rather than resending
   automatically.
5. WHEN the same message is delivered more than once by any transport THE SYSTEM
   SHALL render it once, deduplicating on message id or `clientId`.
6. WHEN human takeover is active THE SYSTEM SHALL poll for new incoming messages
   at the configured interval.
7. WHEN human takeover is not active THE SYSTEM SHALL NOT poll, because no other
   writer can add messages to the conversation.

### Requirement 9: Transport adapters

**User story:** As a developer, I want the chat decoupled from any one messaging
backend, so that the same UI can serve a different transport later.

#### Acceptance criteria

1. WHEN the app boots THE SYSTEM SHALL select exactly one transport adapter from
   configuration, from `salespilot`, `whatsapp`, or `mock`.
2. WHEN any adapter returns a message THE SYSTEM SHALL receive it in one
   normalised internal shape regardless of which adapter produced it.
3. WHEN the `mock` adapter is selected THE SYSTEM SHALL run the full UI with
   scripted conversations and no network access.
4. WHEN the `whatsapp` adapter is selected THE SYSTEM SHALL fail with an explicit
   not-implemented error rather than appearing to work.
5. WHEN the `salespilot` adapter receives a response missing an optional field
   defined in `docs/v0.0/backend/backend-contract.md` Part B THE SYSTEM SHALL continue
   operating with that feature disabled.
6. WHEN a view module needs data THE SYSTEM SHALL provide it from the store and
   the view SHALL NOT perform network requests directly.

### Requirement 10: Composer input handling

**User story:** As a customer, I want the text box to behave the way I expect.

#### Acceptance criteria

1. WHEN the customer presses Enter without a modifier THE SYSTEM SHALL send the
   message.
2. WHEN the customer presses Shift+Enter THE SYSTEM SHALL insert a line break and
   SHALL NOT send.
3. WHEN the composer content wraps THE SYSTEM SHALL grow the input up to a
   maximum of five lines and then scroll internally.
4. WHEN the customer types a recognised text emoticon such as `:)` followed by a
   space THE SYSTEM SHALL replace it with the corresponding emoji.
5. WHEN a message is submitted THE SYSTEM SHALL trim leading and trailing
   whitespace and SHALL reject a message that is empty after trimming.

### Requirement 11: Configuration and branding

**User story:** As the demo operator, I want to adjust presentation without
editing component code.

#### Acceptance criteria

1. WHEN the app boots THE SYSTEM SHALL read business name, avatar initials,
   assistant label, welcome message, transport selection, poll interval, and
   feature flags from a single configuration module.
2. WHEN a user-facing string is displayed THE SYSTEM SHALL source it from the
   strings module and SHALL NOT contain a literal string in a view module.
3. WHEN the business name is changed in configuration THE SYSTEM SHALL reflect it
   in the header and system messages without further edits.
4. WHEN the app renders THE SYSTEM SHALL NOT include any WhatsApp trademark,
   logo, wordmark, proprietary font, or notification sound.

### Requirement 12: Empty, loading, and error states

**User story:** As a customer, I should never face a blank or ambiguous screen.

#### Acceptance criteria

1. WHEN the conversation has no messages THE SYSTEM SHALL display a welcome state
   with the configured welcome message.
2. WHEN the initial conversation history is loading THE SYSTEM SHALL display a
   skeleton placeholder rather than an empty list.
3. WHEN loading history fails THE SYSTEM SHALL display an error state with a
   retry control and SHALL preserve any messages already rendered.
4. WHEN the conversation is reset THE SYSTEM SHALL clear the message list and
   return to the welcome state.

### Requirement 13: Demo support

**User story:** As the presenter, I want a reliable reset and reproducible
scenarios.

#### Acceptance criteria

1. WHEN demo mode is enabled in configuration THE SYSTEM SHALL expose a reset
   control that clears the conversation and restores the welcome state.
2. WHEN the reset control is activated against the `salespilot` adapter THE
   SYSTEM SHALL delete the server-side opportunity for the current customer id.
3. WHEN demo mode is disabled THE SYSTEM SHALL hide the reset control.
4. WHEN the `mock` adapter is active THE SYSTEM SHALL offer at least three
   scripted scenarios covering a nurture path, a hesitation-then-competitor path,
   and a path ending in human takeover.

### Requirement 14: Responsiveness and accessibility baseline

**User story:** As a customer on any device, I want a usable layout; as a
keyboard or screen-reader user, I want to operate the chat.

#### Acceptance criteria

1. WHEN the viewport is at least 900 pixels wide THE SYSTEM SHALL present the
   chat inside a centred phone-shaped frame.
2. WHEN the viewport is narrower than 600 pixels THE SYSTEM SHALL fill the
   viewport with no decorative frame.
3. WHEN the on-screen keyboard appears on a mobile browser THE SYSTEM SHALL keep
   the composer visible.
4. WHEN any interactive control renders THE SYSTEM SHALL give it an accessible
   name and a visible focus indicator.
5. WHEN a new message is appended THE SYSTEM SHALL announce it through a polite
   live region.
6. WHEN text renders THE SYSTEM SHALL meet WCAG AA contrast for its size class.
7. WHEN the customer navigates by keyboard alone THE SYSTEM SHALL make the
   composer, send control, quick-reply chips, retry controls, and jump-to-latest
   control reachable and operable.

> This is a baseline, not a conformance claim. Full WCAG validation needs manual
> assistive-technology testing and expert review.

---

## Stretch requirements

Not part of the first delivery. Do not let these delay Requirements 1–14.

- **[Stretch] S1 — Emoji picker.** A categorised, searchable picker. The baseline
  relies on the operating system emoji keyboard plus Requirement 10.4.
- **[Stretch] S2 — Notification sound.** A self-made sound on incoming messages,
  with a mute toggle that persists.
- **[Stretch] S3 — Background notifications.** Tab-title badge and browser
  notification when the tab is hidden, gated on permission.
- **[Stretch] S4 — Dark theme.** A second token set honouring
  `prefers-color-scheme`, with a manual override.

## Excluded

- **[Out]** Message reactions.
- **[Out]** Image or file upload.
- **[Out]** Voice notes.
- **[Out]** Authentication. Any client may claim any `customer_id`; see
  `docs/v0.0/backend/backend-contract.md`.
- **[Out]** Localisation beyond English.
- **[Out]** Real WhatsApp message delivery.
