# Demo and acceptance checklist — Customer chat UI

A run sheet for presenting the customer chat, and the acceptance gate before
calling the slice set done.

Two ways to demo. Rehearse both, because the first removes every network failure
mode from the presentation:

- **Mock mode** — `config.transport = 'mock'`. No Python server. Fully scripted
  and deterministic.
- **Live mode** — `config.transport = 'salespilot'` against a running backend.
  Shows the real pipeline reacting to free-typed input.

---

## 1. Pre-flight

- [ ] `config.transport` set to the mode you intend to present.
- [ ] `config.features.demoMode` is `true` so the reset control is available.
- [ ] Browser zoom at 100%, window at least 1280px wide for the phone frame.
- [ ] DevTools console open on a second monitor, or closed entirely — never
      visible to the audience mid-demo.
- [ ] Sound muted unless a stretch sound item shipped and the venue suits it.
- [ ] For live mode, the backend is running and seeded:

```powershell
py -3 run.py --serve --seed
```

- [ ] For live mode, confirm the API is healthy before starting:

```powershell
curl http://127.0.0.1:8000/health
```

- [ ] Reset the conversation you intend to use, so the opening state is clean:

```powershell
curl -X DELETE http://127.0.0.1:8000/api/opportunities/C-2001
```

---

## 2. Seeded backend scenarios

`POST /api/seed` (or `--seed`) creates three conversations. These are the
backend's canonical scripts, verified against `salespilot/demo.py`. Use them when
you want the admin console to have populated data behind the chat, and reuse
Sarah's script when you want a predictable five-turn arc.

### Sarah — `C-1024` — nurture into high intent and escalation

| Turn | Message |
| --- | --- |
| 1 | Hi! I'm looking for health insurance with private hospital coverage. |
| 2 | How much does CareSure Plus cost? |
| 3 | Can I add my child to the plan? |
| 4 | It's a bit expensive, and another insurer offered something cheaper. |
| 5 | How do I apply? What documents do I need? |

Backend behaviour to expect, observed from a demo run: the state walks Cold Lead →
Potential Interest → Evaluation & Hesitation, then to High Intent on turn 5; the
score climbs roughly 45 → 47 → 59 → 63 → 83; a HITL case opens on turn 5 for high
intent combined with competitive comparison.

What the **customer** app should show, and nothing more: five outgoing bubbles
with ticks, five replies, a product card around turns 2–4, and on turn 5 the
escalation reply plus takeover treatment. No score, no state name, no signal, no
priority, no next best action.

### Michael — `C-1025` — short factual exchange

| Turn | Message |
| --- | --- |
| 1 | Hi, what's your cheapest basic plan? |
| 2 | Thanks. What does the Essential plan cover? |

Useful for showing a plain informational path with no escalation.

### ABC Pte Ltd — `C-1026` — corporate, escalates on quotation

| Turn | Message |
| --- | --- |
| 1 | We are a company with 120 employees and need corporate health insurance for our staff. |
| 2 | We'd like to proceed with a corporate quotation. How do we sign up? |

Turn 2 escalates, because corporate quotation is outside the AI's authority.
Good for demonstrating handoff quickly, in two turns instead of five.

### Mock-mode scenarios

The mock adapter carries its own scripts so the UI can be shown without a server:
a nurture path, a hesitation-then-competitor path, a path ending in human
takeover, and a deliberate send-failure path for the retry story.

---

## 3. Presentation run sheet

Roughly four minutes. The narrative is the customer experience; the sales
intelligence belongs to the admin console demo.

1. **Open cold.** Show the welcome state: business avatar, name, AI assistant
   label, welcome copy. Point out the AI disclosure in the header — the customer
   always knows they are talking to an AI.
2. **Turn 1.** Type Sarah's first message. Let the audience watch the clock
   become a single tick, the typing dots appear, and the double blue tick land
   when the reply arrives. State plainly that these reflect real request
   milestones, not a cosmetic timer.
3. **Turn 2.** Ask the price question. The product card renders with facts drawn
   verbatim from the knowledge base, and the demo disclaimer sits under it. Note
   that the assistant cannot invent a premium.
4. **Turn 3 and 4.** Family expansion, then the price objection with a competitor
   mention. The replies stay grounded and never disparage the other insurer.
5. **Turn 5.** The application question. Escalation fires: system message, handoff
   banner, header switches to a representative, quick replies disappear. Say why —
   this is a deterministic rule, not the model's discretion.
6. **Resilience aside.** Toggle DevTools offline, send a message, show the failed
   tick and the retry control, reconnect, retry successfully. Emphasise that retry
   reuses the same message identity rather than creating a second bubble.
7. **Reset.** Use the demo reset control and return to the welcome state, ready
   for the next run or for questions.

Optional, if both screens are available: run the admin console beside the chat so
the audience sees the score and priority move while the customer sees none of it.
That contrast is the strongest single moment in the demo.

---

## 4. Acceptance checklist

Sign-off gate for tasks 1–5. Every box is observable; none is a matter of taste.

### Rendering

- [ ] Outgoing right, incoming left, both in rounded bubbles.
- [ ] Tail on the first bubble of each run only.
- [ ] Consecutive same-sender messages within 60 seconds are grouped tightly.
- [ ] A cross-midnight pair shows a date separator; today reads "Today".
- [ ] Every bubble shows `HH:MM`.
- [ ] A message containing `<script>alert(1)</script>` renders as literal text and
      executes nothing.
- [ ] An emoji-only message renders enlarged with no bubble.
- [ ] A URL in a reply is plain text, not a link.

### Send and status

- [ ] Empty composer shows a disabled mic control; typing switches it to an
      enabled send control.
- [ ] Clock, single tick, double blue tick appear in that order on a successful
      send.
- [ ] A failed send shows the danger indicator plus a retry control.
- [ ] Retry reuses the bubble and does not create a duplicate.
- [ ] Enter sends; Shift+Enter inserts a newline.
- [ ] A whitespace-only message is rejected.
- [ ] The composer stays editable while a send is in flight.

### Assistant

- [ ] Typing dots and header typing status appear while in flight and clear
      afterwards.
- [ ] The header labels the assistant as AI whenever the AI is answering.
- [ ] Premium replies keep the full demo disclaimer, untruncated.
- [ ] **No score, priority, signal, state name, or next best action appears
      anywhere in the customer UI.** Verify by searching the rendered DOM for
      `LOW`, `MEDIUM`, `HIGH`, `Potential Interest`, `High Intent`, `nurtur`.

### Scrolling

- [ ] Near the bottom, a new message scrolls into view smoothly.
- [ ] Scrolled up, an incoming message does not move the viewport and the
      jump-to-latest control appears with a correct unread count.
- [ ] Activating it scrolls to the newest message and clears the count.
- [ ] Sending always scrolls to the bottom.

### Content and handoff

- [ ] A product question renders a card with at most four verbatim facts.
- [ ] A premium-bearing card shows the disclaimer.
- [ ] An unknown product renders plain text with no card.
- [ ] Takeover produces a system message, a banner, and a header change.
- [ ] No quick replies render while takeover is active.
- [ ] The composer remains enabled during takeover.

### Resilience

- [ ] Going offline shows the banner immediately.
- [ ] Reconnecting clears it with no page reload.
- [ ] Failed messages are not resent automatically.
- [ ] No message is ever rendered twice.
- [ ] Polling happens only while takeover is active.

### Degradation

- [ ] With the current backend, which returns no `quick_replies`, no chip row
      renders and nothing appears broken.
- [ ] With no server-side message ids, dedupe falls back to `clientId` and the
      transcript stays correct.
- [ ] Selecting the `whatsapp` transport fails with an explicit error rather than
      a blank screen.

### Accessibility baseline

- [ ] The whole app is operable by keyboard alone.
- [ ] Focus is always visible.
- [ ] Every control has an accessible name.
- [ ] New messages are announced via the live region.
- [ ] Reduced-motion mode disables animation and renders static typing dots.

> This baseline is not a WCAG conformance claim. Full validation would need manual
> assistive-technology testing and expert accessibility review.

### Hygiene

- [ ] No console errors or unhandled rejections during a full scenario run.
- [ ] `git status` shows no modification under `salespilot/`, `tests/`, `data/`,
      `run.py` or `requirements.txt`.
- [ ] No network request to any origin other than the configured `apiBase`.
- [ ] Any newly discovered backend gap is recorded in `docs/backend-contract.md`.
- [ ] `docs/frontend-changelog.md` is unchanged unless an entry was explicitly
      authorised.

---

## 5. Known limitations to state plainly if asked

- There is no authentication. Any client can claim any `customer_id` and read that
  conversation. Accepted for the demo; recorded in `docs/backend-contract.md`.
- Delivery ticks reflect client-observed request milestones, not server-issued
  read receipts. The backend has no receipt mechanism.
- Quick replies depend on a backend field that does not exist yet.
- A human representative cannot actually reply yet; there is no endpoint for it,
  so takeover currently changes presentation and stops AI autonomy rather than
  starting a live human conversation.
- Retrying a failed send is safe only once backend idempotency ships. Until then
  the control warns in its accessible description.
- All premium figures are fictional indicative demo rates.
