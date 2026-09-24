# Conversation labels, scoring, and decision rules — v1.0 proposal

**Status:** proposed for team review; no runtime behavior or evaluation cases have been changed by this document.

[中文版](conversation-ruleset-proposal.zh-CN.md)。

This is the human-readable source of truth for a prospective ruleset. After review, a versioned JSON configuration and an offline oracle can be derived from it. Research motivates the distinctions below; it does **not** validate our numeric weights or establish CareSure product facts.

## 1. Scope and evidence

The system assists a sales team in a multi-turn insurance inquiry. Its output has four separate jobs: understand the customer's current request, describe purchase intention, enforce safety boundaries, and identify work needing staff attention. **Customer purchase intention and staff work-queue order are different concepts**, not two HIGH/MEDIUM/LOW scores. Strong purchase interest never authorizes a regulated answer; a safety handoff does not imply purchase interest.

Evidence order for an individual conversation:

1. Staff-maintained records and read-only system facts (for example, an order or case status), when such integrations exist. These establish factual status, not an AI-authored purchase-intention label.
2. The customer's **latest** explicit statement, interpreted with relevant earlier turns.
3. Earlier customer statements, labelled with their time and whether they have been superseded.
4. Model extraction, only with message IDs and short supporting spans; absence of evidence means `unknown`, not a guessed fact.

Approved product knowledge is a separate source. Neither a customer claim, model inference, research paper, nor generic insurance glossary establishes CareSure benefits, price, eligibility, service hours, forms, or processing times. Unsupported facts must be omitted or explicitly marked unavailable; the assistant may offer human help. The corpus and research below inform label design, not customer-facing product answers.

## 2. Labels

These are **conceptual annotations for the new evaluation set**, not an immediate API or database migration. Existing `Intent`, `Signal`, `State`, and `Priority` values remain the v1 wire contract pending explicit implementation approval.

| Field | Values and meaning | Cardinality |
| --- | --- | --- |
| `task_intent` | The primary request in the current turn. Map to the existing intents (`generic`, `price`, `coverage`, `eligibility`, `claims`, `waiting_period`, `payment`, `application`, `comparison`, `family_need`, `corporate_need`, `underwriting`, `human_request`, `complaint`). | One, or `unknown` if unclear. |
| `buying_posture` | `unknown`, `browsing`, `evaluating`, `conditional`, `ready_now`, `deferred`, `declined`. Definitions below. Order/application completion is not a buying-posture label. | One **current** posture per conversation. |
| `objections` | Price, coverage, timing, trust, comparison, needs_other_person, other. | Zero or more; do not infer from demographics. |
| `risk_boundary` | `none`, `unsupported_product_fact`, `personalized_eligibility_or_underwriting`, `medical_advice`, `individual_claim_decision`, `custom_quote_or_negotiation`, `sensitive_data`, `complaint`. | Zero or more; independent of posture. |
| `handoff_reason` | Explicit human request, complaint, negotiation/custom quote, restricted decision, insufficient approved facts, or other existing policy reason. | Zero or more; not a purchase signal by itself. |
| `evidence` | Message IDs, brief exact spans, event provenance, and `clear`/`ambiguous`/`unknown` evidence quality. | Required for every non-default label and score-affecting claim. |

`browsing` means requesting general information, including a single price, benefit, or comparison question; it is **not** a declaration of intent to buy. `evaluating` means weighing suitability, alternatives, or a concern without committing. `conditional` means a purchase statement contingent on an unmet condition (price, another person's approval, eligibility, timing, etc.). `ready_now` requires an explicit present-tense commitment or request to take the next purchase action; “how does application work?” alone does not suffice. `deferred` means no purchase now but possible later; it is not permanent rejection. `declined` is explicit refusal or cancellation of the proposed purchase. A statement such as “I already paid” is conversation evidence requiring verification, not a completion label or permission for the agent to close the lead.

The label is based on the **latest resolved position**, not the highest historical interest. A later “maybe in three months” supersedes “I want to buy now.” A later return to the conversation may supersede deferral, but merely asking a claim-process question must not reactivate a sales lead. Negation, conditional language, the object of the statement (buying vs filing a claim), and timing must be resolved before keyword matching. Ambiguous “yes” or “that one” requires the relevant prior question; if context is unavailable, keep `unknown` and ask briefly.

Existing signal names remain useful as evidence tags, but not as a single ordered funnel: `Hesitation` can coexist with interest; `Competitive` is not an automatic compliance escalation; `Human Request` and `Compliance Risk` are operational flags. The existing model-produced `Conversion` signal must **not** establish an order, active customer, or closed lead. Avoid persisting a keyword alone as proof of a posture.

### Order authority boundary

There is no order integration in the current flow. The agent has no authority to sign, create, confirm, or close an order, mark a customer active, or archive a lead because of conversation text. Only an authorized employee may change the official customer/order lifecycle. If an order database is added, the agent may make an access-controlled **read-only** lookup and accurately relay the returned status, source, and freshness; it may not write the record or infer an order from silence. If no result is available, say it cannot verify the order and offer staff assistance. A customer's claim remains in the conversation and may prompt staff review, but creates no standalone completion label.

## 3. Candidate scoring rule

**Design hypothesis, not empirically calibrated.** Retain the current two-axis structure and 0–100 scales: `fit` describes the potential product/customer match and `behaviour` describes **current** purchase activity. Keep the current fit components (identified need 0–40, product potential 0–40, expansion 0–20) and existing recency buckets initially, so the first comparison isolates the behavioural change. Do not let inferred health, income, or other sensitive traits raise fit. The current combined total may remain a display value, but must not override the two axes or safety gates.

Candidate unadjusted behaviour: `posture_points + readiness_points + engagement_points`, each bounded below. Engagement is the existing depth/urgency component (0–30); urgency requires an explicit time constraint, not model-imagined scarcity. Apply the existing recency multiplier **after** the posture cap. The cap is needed because a long conversation is not, by itself, willingness to buy.

| Current posture | Posture points / 40 | Readiness points / 30 | Pre-recency behaviour cap | Rationale |
| --- | ---: | ---: | ---: | --- |
| `unknown` | 0 | 0 | 30 | No positive purchase evidence. |
| `browsing` | 8 | 0 | 39 | Factual questions do not become a hot lead through message count. |
| `evaluating` | 16 | 5 | 59 | Active consideration, no commitment. |
| `conditional` | 22 | 10 | 69 | Explicit interest, but a condition remains unmet. |
| `ready_now` | 36 | 24 | 100 | Explicit present action; add up to 6 readiness points only for a concrete next action, within 30. |
| `deferred` | 4 | 0 | 25 | Current purchase is postponed, even if an earlier turn was hot. |
| `declined` | 0 | 0 | 0 | No current sales lead; service duties can remain. |

`behaviour = recency_multiplier × min(cap, posture_points + readiness_points + engagement_points)`, rounded consistently with the existing kernel. Recency is based on the last meaningful customer message; an automated or staff message must not renew it. Fit is not reduced merely because the customer postpones; current purchase intention and any sales follow-up recommendation change. A claimed payment is outside this formula: it neither awards purchase points nor closes a lead. The numeric values and cap thresholds above are deliberately provisional. They must pass blinded human ranking and counterfactual tests before replacing `two_axis_v1`.

### Separate customer intention from staff work order

| Output | Question answered | Source and use | Proposed presentation |
| --- | --- | --- | --- |
| Customer purchase intention (`buying_posture`) | “What has this customer currently expressed about buying?” | Conversation evidence, with `fit` and `behaviour` as internal explanatory/evaluation measures. Strong fit alone cannot turn browsing into readiness. | Descriptive stage and evidence, **not** a second HIGH/MEDIUM/LOW badge. |
| Staff work item and queue order | “Which task should an employee handle next?” | Explicit human requests, complaints, restricted decisions, time-sensitive service obligations, and actionable sales follow-up; independent of the customer's purchase intention. | Task type, reason, and a queue position/rank to be designed with staff. Do not yet assign duplicate score bands or SLA promises. |

For example, a customer who declines to buy but raises a complaint has low current purchase interest and may still have an urgent staff task. A ready-to-buy customer may generate a sales follow-up task, but this does not override a more urgent service obligation. Existing qualification and withdrawal safeguards still apply to sales follow-up; uncertain labels require clarification or review rather than exaggerated intention.

The current A/B/C × hot/warm/cold matrix produces the legacy `Priority.HIGH/MEDIUM/LOW` **sales** ranking. Keep it as a regression comparator and frozen-wire compatibility value for now, not as the proposed staff queue. A later implementation must explicitly decide whether to replace or retire that public field, version the contract, and define staff queue ordering with real workflow requirements. The UI should not show two similar “priority” badges or silently reinterpret the legacy value.

## 4. Decision boundary and response rules

| Situation | Assistant may do | Must not do | Handoff behaviour |
| --- | --- | --- | --- |
| General published product, terms, or claims-process question with an approved source | Give a short overview, cite or link the approved item, ask the customer's intent if needed. | Add unsupported benefits, prices, deadlines, forms, or eligibility implications. | Offer human help if approved facts are insufficient. |
| Personal underwriting, medical situation, individual claim outcome, bespoke premium, discount, or binding quote | Acknowledge the question and explain that the decision needs an authorized person. Ask only minimal non-sensitive routing information. | Predict approval/coverage/claim outcome, give medical advice, promise a quote or turnaround, or ask for diagnosis in chat. | Propose handoff; restrict substantive AI answer immediately. |
| Explicit request for a person | Acknowledge and present Confirm/Cancel control plus a text-reply fallback. | Keep selling or require more diagnostic questions. | Propose immediately; create/activate the case only on confirmation, per the approved product flow. |
| Other system-triggered need for staff | Give a concise reason, what the assistant can still answer, and the Confirm/Cancel choice. | Say the case has already been submitted before confirmation. | Propose before creating a case; if the user cancels, retain applicable answer restrictions. |
| Outside staff hours | State only a configured, timezone-aware schedule and actual known availability. Offer to leave a request and limited safe help. | Invent a queue wait, callback deadline, or opening time. | Same confirmation gate; make expected delay clear only if known. |
| Existing human-owned case | Provide safe status/routing information if available. | Auto-reply as though the AI owns the case or overwrite staff drafts. | Update existing case according to staff workflow. |

When a restricted question and a purchase signal occur together, the restriction wins for the **answer**, while the purchase posture remains independently labelled. An urgent handoff never increases the buying score. Standard claims procedure may be answered from approved knowledge; an individual's claim assessment must go to staff. A generic published premium may be cited if current and approved; an individualized quote or negotiated discount may not be invented. A complaint is service work, not automatically a sales opportunity.

The customer can confirm by button or clear text. A bare “yes” must be resolved against the most recent unanswered handoff prompt; if that referent is absent or multiple prompts are pending, ask again. On cancel, clear the pending handoff but do not grant the model authority to answer a restricted question. Record proposal, confirmation, cancellation, case creation, and staff takeover as distinct auditable events. Do not copy sensitive medical details into opportunity profiles or staff summaries; raw chat and debug logs also require access control, minimization, and a separately agreed retention/redaction policy. A rule about derived fields alone does not make raw-message storage safe.

## 5. Worked interpretations (examples, not new evaluation cases)

| Latest customer statement, with relevant context | Proposed labels | Expected action |
| --- | --- | --- |
| “How much is the Plus plan?” | `price`, `browsing`; no purchase signal | Short approved price information if available; no hot-lead promotion. |
| “Does it cover outpatient? I am comparing two plans.” | `comparison`, `evaluating` | Summary and approved detail link; no presumed commitment. |
| “I will buy if you can give me 25% off.” | `price`, `conditional`, `custom_quote_or_negotiation` | No invented discount; offer confirmed staff handoff. |
| After “I want to buy”: “Actually, maybe in three months.” | `deferred`, timing objection | Lower current behaviour and sales priority; do not call it permanent rejection. |
| “No, I am not buying this.” | `declined` | Stop sales pursuit; do not infer inability to afford it. |
| “I have diabetes. Will my application be approved?” | `eligibility`, `personalized_eligibility_or_underwriting`, `sensitive_data` | No prediction or further medical collection; propose human handoff. |
| “How do I file a claim?” vs “Will my claim be paid?” | First: general `claims`; second: `individual_claim_decision` | First: approved procedure only. Second: no decision prediction; propose handoff. |
| “Please connect me to an agent.” | `human_request`, posture unchanged | Show Confirm/Cancel immediately; case only after confirmation. |
| “I already paid yesterday.” with no order integration | Customer claim in conversation; no completion posture or score bonus | Say the order cannot be verified here; offer staff review. Do not assert an active policy or close the lead. |

## 6. How this changes the two teammate drafts and current system

The sales-keyword draft is valuable for candidate phrases, objection types, and the insight that hesitation need not erase interest. Its fixed keyword increments (including 0/6/16/25 in an older 30-point concept) cannot be copied into the current 40/30/30 behavioural model. The new rule requires contextual, temporal, and negation-aware posture labels before points are assigned. The compliance draft provides a good restricted-topic inventory and staff boundary. Its “immediate takeover” language is translated to the team's approved **proposal → customer confirmation → case** workflow, while the restricted answer is blocked at once. Its ban on sensitive data in profiles is extended to summaries, traces, and logs as a design requirement, not a claim that current storage already satisfies it.

Current implementation gaps to verify during a later implementation phase:

- `backend/kernel/scoring.py` can score price/coverage/comparison as purchase intent and uses a historical best-intent high-water mark. Message depth can further increase behaviour despite no commitment.
- `backend/kernel/state_machine.py` does not handle postponement from every high-intent path consistently; generic non-sales contact can revive a dormant lead.
- `backend/kernel/hitl.py` already proposes handoff and `backend/services/conversation.py` waits for confirmation; this customer contract should be preserved.
- `backend/agent/extraction/model_based.py` currently does not pass conversation history into its model call even though service code provides context. Database persistence alone does not repair this.
- Existing 20-case expectations include customer-reported payment as conversion, and the current state machine can mark a lead `Closed / Active Customer` from model-produced `Conversion`. This violates the proposed staff-only lifecycle authority and needs a deliberate compatibility, migration, and test decision; this document does not change the code.
- The current `Priority.HIGH/MEDIUM/LOW` is a sales ranking, not a staff work queue. A distinct staff queue does not yet exist.

## 7. Acceptance gates and sequencing

1. **Review this specification** with sales and compliance stakeholders: annotate disputed examples, confirm staff-only order/customer lifecycle authority, design staff work-item types and ordering separately from purchase-intention stages, and define product KB authority.
2. **Build a new evaluation set later** with multi-turn context, ambiguous/negative/conditional/deferred statements, Singapore English phrasing, safe claims and unsafe claim decisions, and evidence spans. Keep existing cases as regression fixtures until a deliberate migration. Label at least a subset independently by two people and adjudicate disagreements; measure agreement before treating labels as ground truth.
3. **Offline rule check:** feed gold labels and evidence directly into candidate scoring and decision rules; inspect exact outputs plus pairwise invariants: price-only < explicit readiness, conditional < fulfilled condition, deferral after readiness lowers current behaviour, complaint does not imply buying, a claimed payment does not change official lifecycle, and a risky question does not authorize an answer. Evaluate staff task ordering separately. Report confusion and disagreement, not just an overall pass rate.
4. **After persistence/context repair**, run the unchanged model against both old and new evaluation sets. Separate extraction errors from deterministic-rule errors and missing-KB errors. Track unsupported factual claims and wrongful non-handoff as high-severity failures; measure operational cost and latency separately.
5. **Implement selectively only if the evidence supports it:** version labels and scoring (`two_axis_v2`), derive one machine-readable configuration from the approved Markdown, update compatibility mappings, UI explanations, logs, and tests together. Define the staff queue in a separate workflow decision; do not reuse `Priority.HIGH/MEDIUM/LOW` for it. Retain a reversible comparison with `two_axis_v1` during rollout.

No study below supplies insurance-specific score weights or proves that these rules improve conversion. The numbers and priority gates above are falsifiable candidates for the offline and online checks, not claims of external authority.

## References and their limited use

- [CyberAgent SalesTalk dataset and paper](https://github.com/CyberAgentAILab/salestalk-dataset): separates willingness to continue, share information, and accept a sales objective. Simulated Japanese sales conversations; useful conceptual separation, not Singapore insurance calibration.
- [Walmart contextual intent classification](https://aclanthology.org/2020.ecnlp-1.6/): prior turns help resolve short or ambiguous shopping utterances; supports contextual labels.
- [ABCD customer-service dialogue corpus](https://github.com/asappresearch/abcd): scenario and policy-constrained action sequences; supports explicit decision boundaries, not our particular insurance policy.
- [CLINC out-of-scope intent dataset](https://github.com/clinc/oos-eval): supports an `unknown`/abstain path rather than forced labels; mostly single-turn general-domain data.
- [CoSEM Singapore English corpus](https://github.com/wdwgonzales/CoSEM): helps devise local language variation tests; not a sales or insurance corpus. Check non-commercial license limits before reusing text.
- [Singapore Life Insurance Association 2024 trust survey](https://www.lia.org.sg/media/4390/iccsc_insurance-trust-indicator-study-2024_final-report.pdf): local insurance service/trust context; does not justify numeric score weights or WhatsApp volume assumptions.
- [LIA glossary](https://www.lia.org.sg/tools-and-resources/insurance-terms/): generic insurance terminology only, never a source of CareSure product facts.
- [InsuranceQA](https://github.com/shuzi/insuranceqa) and [JDDC](https://aclanthology.org/2020.lrec-1.58/): question phrasing and multi-turn commerce examples respectively, with domain and license limitations.

The source critique and broader research review are in [Conversation intent research and revision plan](conversation-intent-research-and-revision-plan.md). The companion [Persistence and evaluation repair plan](persistence-repair-plan.md) must be completed before the proposed online comparison is interpreted as a model capability test.
