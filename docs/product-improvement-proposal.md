# SalesPilot improvement proposal — 2026-09-23

Status: **implemented for local demo; verification in progress**. This is a cross-track product plan, not a replacement for the backend plan or frontend changelog. The current v1 API contract remains frozen; accepted wire additions are recorded in `docs/api/interface-v2.md`.

## Product outcome and boundaries

Help a CareSure representative understand and act on a customer enquiry quickly, while keeping customer conversations concise and safe. The customer sees no scoring or internal diagnostics. Priority, score and escalation remain backend decisions. The assistant remains visibly labelled AI. Premium disclaimers must remain visible whenever premium information is shown. No real WhatsApp integration, authentication or multi-tenancy is implied by this proposal.

## Current baseline verified in code

| Area | Current behaviour | Consequence |
| --- | --- | --- |
| Human handoff | `backend/kernel/hitl.py` decides; `backend/services/conversation.py` creates a case and sets `human_takeover` immediately. | No customer confirmation step. |
| Model tools | Five tools are registered in the observation agent in `backend/agent/runtime.py`; the reply-composition agent has no tools. | There is no structured question tool. |
| Guardrails | Tool calls, model requests, tokens and cost are bounded by `backend/config.py` and `backend/agent/runtime.py`. | Any new tool must fit the existing budget rather than expand it silently. |
| Admin refresh | `refreshIntervalMs` is set to 15 seconds in `frontend/admin/js/config.js`; Inbox/Cases refresh on navigation or manual action. | The configured interval does not currently run. |
| Message formatting | Customer AI text uses `frontend/customer/js/markdown.js`; admin transcript renders raw text via `textContent`. | Markdown markers such as `**` are visible in admin. |
| Explainability | Score dimensions and run telemetry exist, but score history does not preserve per-rule evidence/message references. | A trustworthy scoring explanation requires backend provenance, not UI reconstruction. |
| Knowledge links and service hours | The approved product JSON has facts but no verified source URLs; no representative hours or response-time configuration was found. | Add a real schedule source before quoting hours; do not invent links or a wait estimate. |

## Proposed experience

### 1. Staff handoff brief

Add **Generate brief** on an active case and on the linked conversation. It is an on-demand action, not an automatic extra model call on every turn. The result is a draft for staff, never sent to the customer automatically.

The brief should fit one screen: customer intent; product and requested action; confirmed facts versus unresolved questions; reason for handoff; urgency/priority and its evidence; 3–5 keywords; last relevant customer quote; suggested next step. Clearly label unknowns and the source message IDs. Prefer a deterministic structured extraction and approved facts, with an optional model pass for concise wording. Staff can regenerate and copy it. Do not let the model alter priority, score, customer facts or case status. Cache by latest conversation message ID to avoid repeated cost; show the generation time and whether the result is stale.

### 2. One confirmation before every handoff

Insert a persisted `PENDING_CONFIRMATION` step between *handoff recommended* and *case created/taken over*. This is a backend state transition, not only a prompt instruction. For every trigger, offer **Confirm human help** and **Cancel / continue with AI**. Accept typed confirmations/cancellations as well as a UI control. Confirmation creates/updates one case idempotently; declining closes the pending request without claiming that an unsafe topic can be handled by AI. A new substantive trigger may reopen confirmation; repeated background evaluation of the same trigger must not nag the customer. Define expiry and retry behaviour before coding.

There are two distinct entry paths. If the **customer explicitly asks for a person**, show the confirmation control immediately, without model persuasion or an extra qualification question. If **the system recommends a person** for any other reason, first provide one short reason (“I cannot make that decision here” / “A representative can complete the next step”), then ask for confirmation. Both paths use the same backend state and accept typed “yes/no” in a real messaging channel. A browser demo may also show two buttons, but the transition must never depend on buttons being available.

The customer copy should contain only verified information: a short answer or factual context if safe, why a representative is useful, what will happen on confirmation, and the actual service hours. Add a backend-owned schedule and a read-only availability service/tool (e.g. `get_staff_availability`) using the configured Singapore timezone and the current time. It should return open/closed and the next opening, not let the model calculate hours. A time-of-day tool alone cannot establish business hours; it needs an approved schedule and holiday/exception policy. Show a numeric response-time estimate only if separately backed by queue/staff data; opening time is not a response-time promise. For medical, underwriting, claims and other restricted decisions, do not add advice merely to make the message persuasive. The AI does not say a case is submitted until confirmation succeeds.

Outside service hours, show the next verified opening. If the customer confirms, queue the request for that opening; also offer to continue with the AI on topics it is allowed to answer while waiting. Do not block the human request or imply that the AI can make a restricted decision.

Example (purchase intent): “CareSure Plus includes [one approved fact]. A representative can help with the application and confirm the details. Shall I pass this to the team? [Confirmed service hours or honest availability statement].”

Example (restricted question): “A representative needs to review that question; I can’t decide it here. Would you like me to pass this conversation to the team?”

Example (explicit human request, closed hours): “Our team is currently offline and next opens at [verified time, Singapore time]. I can queue your request now, or help with general plan information meanwhile. Should I queue it?”

The wording pattern is a recommendation, not a copied third-party prompt. It follows sales discovery guidance to clarify the need, confirm understanding and make the next step explicit: [Salesforce relationship selling](https://trailhead.salesforce.com/content/learn/modules/relationship-selling/collaborate-with-the-customer), [Salesforce sales process](https://trailhead.salesforce.com/content/learn/modules/build-a-sales-process/learn-about-the-sales-process). The team should approve the insurance-specific copy.

### 3. Structured question tool

Add an observation-stage tool tentatively named `propose_customer_question`. The model may propose a needed field and contextual wording, but the backend validates it against an allowlist/question catalog, checks already-known facts, caps choices, and emits a structured customer-safe question. **Text is the canonical interaction:** send a short numbered list, followed by “Reply with a number, or describe something else.” Accept a number, the option label, or a natural-language answer. The browser demo may additionally render chips/buttons, but their availability must not change the underlying state machine. A typed answer has a length limit and is treated as untrusted customer text. The backend validates and records the selected option or free text with its question ID and source, then resumes the normal conversation pipeline. Ask one question at a time; do not ask for sensitive medical details or repeat a field already known.

Suggested first catalog: reason for contact (learn/compare/apply/speak to staff), product of interest, individual/family/group cover, broad desired follow-up time. Avoid collecting identifiers, health conditions or payment data. Existing `quick_replies` are suggested next utterances, not a structured field capture; the new tool should not simply rename them. The model can suggest an allowed field, but must not create arbitrary form schemas or business rules.

For example: “What would you like help with? 1. Compare plans 2. Check an indicative price 3. Apply 4. Something else — tell me in your own words.” This works even when a channel supports only plain text. WhatsApp Business Platform does offer some interactive reply buttons and lists, but not an arbitrary web form with a custom free-text option; the real transport in this project is still a stub. Channel-specific interactive formatting is a later adapter enhancement, not a dependency of the core feature. See Meta's [reply-button API example](https://www.postman.com/meta/whatsapp-business-platform/request/x0kd1at/send-reply-button).

Proposed payload sketch for v2 review, **not a committed contract**:

```json
{
  "question_id": "q_...",
  "field": "contact_reason",
  "prompt": "What would you like help with?",
  "options": [{"id": "compare", "label": "Compare plans"}],
  "allow_other": true,
  "source": "approved_catalog"
}
```

### 4. Automatic refresh

Poll Inbox and Cases while the admin tab is visible, initially at the existing 15-second configuration. Poll the selected conversation only when needed and avoid duplicate in-flight requests. Pause when hidden or offline; back off after failures and show the last-updated/stale state. Preserve selected row, drafts, open disclosures and scroll position; ignore older responses that arrive after newer ones. **Debounce is useful for typing, search and autosave, but it does not protect a local draft from a polling render that replaces its input node.** Keep the draft in local UI state and update only changed server data; never overwrite a dirty input. Manual refresh remains available. Do not poll full model traces or trigger model generation. The customer app already has incremental polling for human takeover; retain that separate behaviour.

### 5. Consistent, safe message rendering

Use the same small, dependency-free Markdown subset in customer and admin AI-generated messages: paragraphs, simple lists, emphasis and bold. Parse into DOM nodes and put content into `textContent`, never raw HTML. Literal customer/staff messages should not unexpectedly be formatted. Handle unmatched markers as ordinary text or a deliberate fallback, and keep mandatory premium disclaimers unhidden. Because the apps intentionally have self-contained static code, keep implementations/fixtures aligned without introducing a build step.

### 6. Admin information hierarchy

Inbox row first glance: **human-help status/priority**, customer and latest need, score, one-line reason, 3–5 keywords, age of request. The active conversation first glance: short need summary, handoff reason, priority/score with a compact explanation, latest customer message, and the representative action. Cases first glance: priority, time waiting, customer, reason, keywords, and the primary next action. Priority is the operational order; the score is supporting context, not an alternate ranking invented by the UI.

Move the full score breakdown, signal history, agent activity, raw tool calls and long summaries behind a disclosure or the debug route. Keep a visible “Why this priority?” affordance. The **Generate brief** button belongs beside the representative action, with an accessible loading/error state. Reduce type styles, badge count and repeated metadata; do not hide actionable compliance warnings.

### 7. Progressive customer answers

For ordinary information requests, the default answer is a direct one- or two-sentence overview, at most two relevant approved facts, and one helpful clarifying question or detail choice. Offer a “See details” path or approved source link. Currently the KB has no verified URLs, so a link must not be fabricated; an expandable detail message/card is the initial option. When the customer asks for specifics, provide the fuller approved facts. If quoting a premium, show the complete required disclaimer regardless of brevity. Apply the concision rule to model and deterministic fallback replies; keep the safety/knowledge gates unchanged.

### 8. Dedicated debug route

Add an admin `#/debug` route with three panels:

1. **Model run:** selected conversation/run, inputs and outputs, tool calls/results, model/provider, token/cost/latency data, budget usage, fallback reason and correlation IDs.
2. **Score and priority:** each dimension, points, exact rule/version, supporting signal and source message ID/quote, recency calculation, priority matrix result and handoff trigger. This requires backend-generated evidence records; the frontend must not recompute scores.
3. **Backend/API:** `/health` status and degradation, recent request/response metadata and bodies where safely retained, status codes, duration, correlation ID and error. A browser gateway can show its own observed calls, but server-side history requires a bounded backend trace store.

The admin console is for internal staff, so the proposed debug view may show full prompts, replies, scoring evidence and customer conversation data. Redact only credentials and authentication secrets (API keys, passwords, bearer tokens, cookies and equivalent fields); keep bounded retention and an explicit local-demo enable switch so logs do not grow without limit. **Current code has no authentication**, so “internal-only” is an operational assumption, not an access control: this route and the existing admin API must stay on localhost or a trusted private network. Public deployment of this diagnostic view requires real authentication/network isolation first. A hidden nav link is not security. The route is for debugging, not the primary work surface.

## Existing agent tools and where to maintain them

| Tool | Purpose | Implementation |
| --- | --- | --- |
| `lookup_product_fact` | Retrieve one approved product fact. | `backend/agent/tools/knowledge.py` |
| `compare_products` | Compare approved facts across plans. | `backend/agent/tools/knowledge.py` |
| `list_products` | List known products. | `backend/agent/tools/knowledge.py` |
| `conversation_summary` | Summarise known opportunity context for the model. | `backend/agent/tools/opportunity.py` |
| `request_human_handoff` | Record a handoff proposal; it does not create a case. | `backend/agent/tools/handoff.py` |
| `propose_customer_question` | Propose an approved question field; the backend decides whether to ask. | `backend/agent/tools/questions.py` |
| `get_staff_availability` | Read the configured Singapore-time representative schedule. | `backend/agent/tools/availability.py` |

Registration and model-visible descriptions live in `backend/agent/runtime.py`; shared tool context/recording lives in `backend/agent/tools/__init__.py`. Approved product facts live in `backend/knowledge/data/knowledge_base.json`; the three initial question fields live in `backend/knowledge/questions.py`; the representative schedule is configured with `SALESPILOT_STAFF_HOURS_JSON` and optional closed dates. Safety and model instructions live in `backend/agent/policy.py`; deterministic decisions in `backend/kernel/`. Existing per-segment limits (3 tool calls, 5 requests, 12,000 total tokens, 2,500 output tokens, US$0.03 cost) stay in force pending evaluation. The provider may lack pricing metadata, in which case the library cannot enforce the dollar cap even though request and token caps still apply.

## Delivery sequence and review gates

1. **Decide product semantics and v2 contract.** Agree confirmation expiry/repeat behaviour, schedule/holiday source, allowed question fields, brief schema and credential redaction. Publish reviewed `interface-v2.md`; do not edit v1.
2. **Backend state and evidence.** Add pending confirmation transitions, question validation/storage, on-demand brief endpoint, score provenance and safe diagnostics. Keep existing model limits and fail closed where appropriate.
3. **Customer interaction.** Render confirmation and structured choices, ensure short default answers and safe disclosure, align Markdown handling.
4. **Admin experience.** Reorder Inbox/Cases, add brief action and polling, move detail into `#/debug` and disclosures.
5. **Verification.** Run existing backend/frontend suites; manually check model-enabled and fallback paths, double-confirm/idempotency, explicit-human and restricted-topic cases, stale polling, redaction and disclaimers. New test code needs separate consent under `AGENTS.md`.

## Acceptance checks for the eventual build

- No case or takeover flag is created before explicit customer confirmation; one confirmation creates only one case, including on retry.
- A declined request leaves a clear path to ask again but does not let the AI answer a restricted question.
- The brief is one-screen, source-grounded, staff-only, and does not change business state.
- The new question tool never invents unapproved fields/options or asks for already-known information; text-only channels accept numbered choices and a free-form “something else” reply.
- Admin queue updates without manual refresh, without losing a draft/selection or spawning overlapping requests; debounce alone is not considered draft protection.
- AI formatting is consistent on both surfaces, safe against injected HTML, and shows required disclaimers.
- Inbox/Cases prioritise action, priority, score, reason and keywords; low-level traces live in `#/debug`.
- Debug evidence can explain each score from a rule and source; diagnostics never expose credentials and are limited to trusted local/private use until access control exists.

## Decisions requested from the team

1. Set the real representative schedule and its holiday/exception owner. Recommended: Singapore time, backend-owned, with next-opening information; do not equate opening time to response ETA.
2. Review the initial safe question catalog: contact reason, cover type and broad follow-up time. Product interest is already captured by existing detection and can be added as a fourth structured field later if needed.
3. Confirm the demo network boundary for full debug data. Recommended: localhost/private network only until real access control exists; redact credentials but keep other diagnostic content.
