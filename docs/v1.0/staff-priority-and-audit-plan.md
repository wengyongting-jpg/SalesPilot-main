# Staff priority, score provenance, reply evaluation, and model cost

**Status:** Approved direction and implementation plan; not yet implemented. Recorded 2026-09-26. The owner approved manual staff takeover from any conversation, a closed-list reason selector, and a staff-processing priority separate from the sales opportunity score. Numerical thresholds and the exact staff-priority mapping below are candidate policy until reviewed against cases.

## 1. Current behavior and terminology

- A case in `Open` status has been created for staff but has not been claimed. `Taken Over` means a representative owns the conversation and the AI must stop replying. Case status is a workflow state, **not** a priority tier.
- Today staff can claim an existing Open case, but cannot create and claim a case directly from an arbitrary conversation. `POST /api/admin/opportunities/{id}/messages` rejects a staff reply unless takeover is already active.
- The existing 0–100 `ScoreCard.total` is the mean of **fit** and **buying behaviour**, not pure purchase willingness. Its `HIGH/MEDIUM/LOW` `priority` is a separate sales-priority matrix derived from those axes. Neither is staff-processing urgency.
- The current case API does not expose a score or either priority. The admin adapter expects `priority` and `score` anyway, so presentation-only changes cannot deliver this design.
- The frozen v1 wire contract must not be edited in place. New fields and actions need a versioned API delta and compatible admin adapter.

## 2. Two independent routes

| Route | Question | Inputs and authority | Staff presentation |
| --- | --- | --- | --- |
| Sales opportunity | How commercially promising is this enquiry? | Existing deterministic fit/behaviour scorer. Keep the internal matrix-derived sales priority distinct from the displayed 0–100 total. No model-authored score. | Label the number **Sales opportunity score** and explain that it combines fit and buying behaviour. Do not relabel it as a probability of purchase or as a staff service priority. |
| Staff processing | Which human task should be handled first? | Deterministic policy over the case reason, restricted/complaint/payment-service flags, case status, and any explicitly approved time-sensitive evidence. It must not inherit sales score or sales priority. | **High / Medium / Low staff priority**, each with text and an accessible three-level colour treatment. The reason is visible next to the tier. |

The first staff-priority policy should be small and auditable. Candidate ordering for review: payment/order failure, complaint, restricted individual decision, and explicit human request are High; actionable sales follow-up and other requested service work are Medium; optional routine staff assistance is Low. A customer's purchase likelihood does not raise a complaint's or payment issue's tier, and a high-value lead does not outrank a High service case by virtue of its score. Do not invent service-level deadlines or contact-time promises. Test the mapping with staff before treating the tiers as calibrated operations policy.

## 3. Manual staff intervention

Add a **Take over** action to an arbitrary conversation, independent of customer-initiated handoff. Its reason is required and selected from a closed list; there is no free-text or model-generated reason on this path. Proposed options are:

| Reason code | Staff label |
| --- | --- |
| `customer_requested_staff` | Customer requested a person |
| `payment_or_order_issue` | Payment or order issue |
| `complaint_or_service_issue` | Complaint or service problem |
| `restricted_decision` | Restricted insurance/claim decision |
| `sales_follow_up` | Sales follow-up |
| `general_staff_assistance` | Other staff assistance |

The selected code is stored separately from customer-facing wording. The server validates it against the allow-list and determines staff priority; the browser never calculates the priority. An employee-originated takeover does **not** need a new customer confirmation, but must create or claim the one active case and set `human_takeover` atomically before staff can reply. If an Open case exists, claim it; if already Taken Over, return an idempotent outcome rather than duplicating it. Preserve the existing customer-confirmation gate for **AI-proposed** handoffs. Record the source (`staff_manual` or `ai_proposal`), selected reason, timestamp, case ID, and a staff identifier if one is available; the demo has no authentication, so a typed name must not be presented as verified identity. Closing the case follows the existing autonomy-resumption policy, which should be explicitly tested.

The admin Inbox should expose the manual action even without a case. The Cases view should clearly separate Open (waiting), Taken Over (owned), and Closed (finished) from High/Medium/Low staff-processing priority. Queue ordering should put unresolved High staff tasks first within the appropriate workflow status; sales score is not a service-queue tie-breaker. Display the sales opportunity score in its own secondary area with a short definition; do not show two visually identical `HIGH` badges without distinct labels.

## 4. Score provenance as structured audit data

The existing score explanation reproduces arithmetic but cannot cite the source message for each contributing signal: `Opportunity.evidence_sources` is not currently populated per signal. Logging only the final number or raw model transcript does not solve this.

For each score update, persist a compact, versioned audit record with: opportunity and customer-message IDs; scorer version; accepted current and historical inputs; each dimension's points and applied rule ID; source message IDs or trusted event IDs; any caps/decay; resulting sales score and sales priority. When a historical input contributes, cite its **original** message rather than the latest one. Keep model observations, rule acceptance, and final arithmetic distinguishable. Do not duplicate medical details or full message text in the audit record; authorized staff can resolve message IDs to the transcript. Mark provenance for pre-migration scores as unavailable instead of manufacturing it.

Expose this breakdown on the existing staff debugging route and keep Inbox/Cases concise. Verify that the displayed explanation for a given score-history entry reproduces that entry, not merely today's score. This is an observability and persistence task, not a request for the model to justify its own score.

## 5. Reply-quality evaluation after human review

The existing multi-turn suite checks labels and a few safety invariants; passing it does not establish answer relevance or usefulness. The owner will arrange a human review of case labels before new response-quality assertions are adopted. Preserve the reviewed cases as a held-out set rather than optimizing prompt wording directly against every gold response.

The subsequent evaluation design should score separate dimensions: correct task interpretation, correct action/handoff timing, supported fact selection, absence of unsupported claims or unexecuted-action promises, concise and relevant wording, appropriate follow-up question, and safe handling of restricted requests. Review full multi-turn transcripts, not isolated customer messages. Report critical failures individually alongside aggregate results; a high average must not hide a false payment confirmation or unsafe insurance decision. Do not add evaluation cases or test code without the repository-required owner consent.

## 6. Claude Sonnet 4.5 usage and budget

For `global.anthropic.claude-sonnet-4-5-20250929-v1:0`, AWS identifies the `global.` ID as a global cross-Region inference profile. Published global standard pricing for Claude Sonnet 4.5 is approximately **USD 3 per million input tokens and USD 15 per million output tokens**. This is a dated **reference price**, not proof of the organiser gateway's billing terms; caching, region/source, gateway markup or credits, and future price changes can alter the charged amount.

References checked 2026-09-26:

- AWS global profile and source-Region billing: <https://docs.aws.amazon.com/bedrock/latest/userguide/global-cross-region-inference.html>
- AWS Sonnet 4.5 global pricing table: <https://aws.amazon.com/jp/blogs/news/amazon-bedrock-now-supports-japan-cross-region-inference/>
- Bedrock Converse response `usage` (tokens, not a dollar-charge field): <https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_Converse.html>

The service uses an **OpenAI-compatible gateway**, not a direct Bedrock Converse client. Its real response may contain usage counts or gateway-specific extensions; inspect one redacted actual response before assuming which fields exist. Prefer provider-reported input/output/cache token counts. If the gateway provides an authoritative per-request billed cost, record it separately as `provider_reported`; otherwise calculate `estimated_usd` from a reviewed, versioned price table and label it as an estimate. Never silently treat missing usage or unpriced models as zero cost. Reconcile estimates against organiser billing/credits when available.

The current token, request, tool and per-segment cost limits remain in place. Confirm that every model request within extraction, memory and response work is counted once, and enforce a whole-customer-turn budget across segments; adding a reply-selection step must not silently grant another full cost allowance. In the admin trace show reported tokens, estimated or provider-reported dollars, pricing basis/version, and an explicit `unknown` state where accounting is incomplete. Do not claim that a USD limit is hard-enforced for this model until the model ID, price path and gateway usage behavior have been verified.

## 7. Suggested implementation and acceptance order

1. Define and review the staff reason allow-list, candidate High/Medium/Low policy, and versioned API delta. Confirm active-case and close/resume semantics before coding.
2. Implement the server-side manual takeover transaction and independent staff priority, then adapt Inbox/Cases with distinct labels, colours and ordering. Assert no duplicate case, no AI reply after takeover, and no priority derived in the browser.
3. Persist per-turn score provenance and expose it in staff diagnostics. Verify historical-input message IDs and arithmetic reproduction; retain truthful `unavailable` provenance for older records.
4. Audit one redacted configured-model response, add the reviewed Sonnet 4.5 rate and estimate/reporting path, and test missing-usage, cache-token and unknown-price behavior. Verify aggregate turn budgets.
5. After human case review, agree the reply-quality rubric and acceptance thresholds, then add approved tests and run bounded offline/live evaluations.

This plan does not change runtime behavior, add tests, run a paid model, or mutate the frozen v1 contract by itself.
