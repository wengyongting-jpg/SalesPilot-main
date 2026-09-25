# SalesPilot conversation intent research and revision plan

Status: **proposal for review; not implemented**  
Branch baseline: `salespilot-v1.0`  
Scope: sales-intent interpretation, compliance routing, evidence, and evaluation. This document does not change product facts, code, labels, or the public API.

## Decision to review

Keep the two teammate drafts as **design inputs**, not executable policy. The first draft, *SalesPilot 销售关键词库与意向度评分联动规则* (`销售关键词库与意向度.doc`), supplies candidate phrases and useful signal categories. The second, *敏感信息处理与合规升级* (`合规边界(1).docx`), supplies safety boundaries and acceptance examples. Neither establishes the frequency, predictive value, or legal sufficiency of its examples.

For v1.0, interpret each customer turn in its conversation context. Separate **what the customer wants now**, **readiness to buy now**, **objections or timing**, and **whether the assistant may answer**. Treat keywords as recall-oriented hints; require quoted customer evidence and a deterministic policy decision before changing priority, asserting conversion, or initiating a handoff. Public datasets can inform the label guide and stress tests; only approved CareSure materials may supply CareSure product facts.

## What the two drafts get right and where they need revision

| Draft | Retain | Problem to resolve before implementation |
| --- | --- | --- |
| Sales keywords and intent scoring | Reuse the existing detector, scoring, state, and HITL pipeline; do not create a parallel agent or scoring system. Distinguish hesitation, competition, withdrawal, negotiation, and explicit human requests. | Phrase-to-score mappings are proposed without observed customer frequencies, calibration, or negative examples. “How much?”, “I am comparing”, and “I want to buy now” are not the same buying commitment. The draft's single-score increments and priority bands do not match the current two-axis fit/behaviour score in `backend/kernel/scoring.py`. Historical peak intent must not hide a current postponement or refusal. A claimed payment is not verified conversion. Its suggested `salespilot/...` paths are not the repository's current `backend/...` layout. |
| Sensitive information and compliance escalation | No personalised underwriting, medical, claim, price, or coverage decision; no invented facts; no unnecessary medical follow-up; human ownership once a case is accepted. | “Medical/claims mention” is broader than “personalised decision”: ordinary claims-process questions and approved general product explanations should remain answerable. The draft treats detection, customer consent, case creation, and human takeover as one immediate step; the current flow offers Confirm/Cancel first. Safety must apply while confirmation is pending, but the customer must not be told a case exists before it does. Its profile-only privacy rule does not cover raw messages, case briefs, telemetry, or logs. “No sensitive text stored” cannot be claimed without an explicit retention and redaction design. |

The documents also contain customer-facing sample copy that presumes approved discounts, comparison material, follow-up deadlines, or confirmed handoff. These may only be used when the corresponding facts or actions exist. This is a product and engineering review, not a determination of Singapore legal compliance.

## Evidence reviewed and appropriate use

The strongest cross-industry material concerns *conversation behaviour*, not insurance facts:

| Primary source | What it contributes | Limit for this project |
| --- | --- | --- |
| [User Willingness-aware Sales Talk Dataset and paper](https://github.com/CyberAgentAILab/salestalk-dataset), [COLING 2025](https://aclanthology.org/2025.coling-main.742/) | 109 sales dialogues and utterance-level judgments of willingness to continue, provide information, and accept the sales objective. Motivates separating engagement from purchase readiness and tracking change by turn. | Japanese, simulated setting, CC BY-NC-SA 4.0. Not a Singapore conversion-rate benchmark or production training corpus. |
| [JDDC original paper](https://aclanthology.org/2020.lrec-1.58/) and [Chinese customer-service dialogue corpus](https://github.com/cooelf/DeepUtteranceAggregation) | Real multi-turn e-commerce service language and intents such as product, price, order, and after-sales questions. Candidate paraphrases and multi-turn failure patterns. | Different products and market; access and licence must be checked for each corpus before copying samples. |
| [Action-Based Conversations Dataset](https://github.com/asappresearch/abcd) | More than 10,000 human-to-human scenario conversations with 55 intents and policy-constrained actions. A model for evaluating required steps, not just a one-turn label. | Scenario-collected, not organic insurance/WhatsApp traffic. Repository has an MIT licence; verify any downstream data use separately. |
| [CLINC out-of-scope evaluation dataset](https://github.com/clinc/oos-eval) | Tests whether a system recognises an unsupported request rather than forcing it into a known intent. | English and single-intent; does not measure multi-turn sales readiness. |
| [InsuranceQA](https://github.com/shuzi/insuranceqa) | Real-world insurance questions for terminology and question-form discovery. | Single-turn, non-Singapore answers, research-only notice. Never use its answers as CareSure policy facts. |
| [CoSEM Singapore English Messages](https://github.com/wdwgonzales/CoSEM) | Local messaging phrasing and Singlish variants for robustness cases. | Not a sales corpus; CC BY-NC-SA 4.0, with residual privacy risk noted by its maintainers. |

Additional research directions:

1. **Conversation context and intent changes.** [Walmart's contextual intent study](https://aclanthology.org/2020.ecnlp-1.6/) found that preceding utterances helped classify later e-commerce requests. We should test elliptical replies, corrections, negation, and changed purchase timing, not score an isolated phrase.
2. **Decision friction and question design.** [A qualitative health-plan selection study](https://www.sciencedirect.com/science/article/pii/S2590229623000242) identifies difficulty with terms, finding information, and comparing plans. It suggests concise clarification and comparisons as candidate interventions, not a universal sales script; its US sample is not locally representative. [Follow-up-question experiments](https://www.hbs.edu/ris/Publication%20Files/Huang%20et%20al%202017_6945bc5e-3b3e-4c0a-addd-254c9e603c60.pdf) concern perceived responsiveness, not sales conversion.
3. **Singapore service expectations and channel evidence.** The [Insurance Trust Indicator Study 2024](https://www.lia.org.sg/media/4390/iccsc_insurance-trust-indicator-study-2024_final-report.pdf) surveyed 3,044 existing consumers and 306 SME managers in Singapore and identifies follow-through, knowledgeable help, clear claims information, and data protection as trust-related drivers. Its sample does not establish WhatsApp enquiry volume, staffing shortage, or SalesPilot ROI.
4. **Domain-authoritative terminology and safe non-answers.** The [Life Insurance Association Singapore terms](https://www.lia.org.sg/tools-and-resources/insurance-terms/) can validate generic vocabulary. Product-specific price, coverage, eligibility, and process claims still require the approved CareSure knowledge base and an evidence-linked answer.
5. **Data provenance and rights.** Track whether each example is an approved product fact, public research sample, synthetic test, or consented real transcript. Keep non-commercial/public research corpora out of any commercial training or redistributed fixture until rights and privacy have been reviewed.

## Interpretation for SalesPilot

Use independent, evidence-bearing fields rather than one “intent score”:

- **Current task:** product information, comparison, price, application, claim process, complaint, explicit human request, or unknown. Multiple tasks may coexist.
- **Buying position now:** browsing, evaluating, conditional interest, ready to proceed, postponed, declined, or unknown. This is not a claim about eventual conversion.
- **Constraints and willingness:** price concern, timing, family approval, willingness to answer a question, and request for no further sales contact. These explain the next action; they should not all become negative points.
- **Authority and safety:** general approved fact, unsupported fact, personalised decision, sensitive information, negotiation, or complaint. This determines what the system may say, independent of lead value.

Each field needs an evidence span or turn reference, an `unknown` option, and an explicit distinction between *observed words* and *inferred meaning*. For example, “How much is Plus? Maybe in a few months” supports a price enquiry and current postponement, not “ready to buy.” “I paid” is a customer statement; absent a trusted payment event, it must not be represented to staff as verified payment. The agent may extract a candidate observation; existing backend rules remain the authority for score, state, allowed reply, and handoff.

The current repository already separates fit from behaviour in `backend/kernel/scoring.py`, evaluates handoff reasons in `backend/kernel/hitl.py`, stores a pending handoff before confirmation, and keeps a JSON product knowledge base. `backend/agent/extraction/model_based.py` currently accepts context but calls the model with only the latest text; the [persistence repair plan](persistence-repair-plan.md) already marks continuity as a separate task. These are review starting points, not claims that the new taxonomy is already implemented.

## Next-stage modification plan

The rounds below are proposals, **not authorisation to change code or create tests**. Resolve the existing persistence repair's state round-trip before treating cross-request intent results as reliable. Preserve the frozen v1 customer contract unless a separate API change is approved.

| Round | Work and concrete output | Acceptance and review gate | Estimate |
| --- | --- | --- | --- |
| 0. Baseline and conflict register | Map every rule in the two drafts to current detection, score, state, handoff, knowledge, storage, telemetry, and eval paths. Record conflicts, obsolete path names, and decisions needed; do not copy draft values into code. | One traceable rule-to-code table; explicit decisions for general claims vs personalised claims, confirmation-before-case, claimed vs verified payment, and raw-sensitive-text retention. | 45–75 min |
| 1. Label guide and small annotation set | Draft definitions for current task, present buying position, constraints, safety, evidence, and unknown. Include 30–50 *multi-turn* examples covering price-only, comparison, future purchase, explicit refusal, immediate purchase, negation, changes of mind, Singlish/code-switching, and human requests. Seek permission before adding them as tests. | Two reviewers can independently label a pilot set; disagreements are logged and definitions revised. No numeric weights yet. Keep development examples separate from held-out evaluation. | 2–3 h plus reviewer time |
| 2. Deterministic boundary design | Specify rule precedence and pending-handoff behaviour: block personalised answers immediately; offer/record customer confirmation according to the approved flow; create a case only at the defined transition; stop automated customer replies during takeover. Define allowed fields and retention/redaction for message, profile, brief, run trace, and logs. | Decision table covers ordinary product/claims-process questions without blanket escalation, and restricted cases cannot yield a decision or fabricated fact. Privacy and handoff semantics have owner approval. | 1.5–2.5 h |
| 3. Contextual extraction and scoring integration | After round 2 approval, pass bounded recent turns plus existing structured state to extraction; output evidence-linked observations, not a direct priority. Adapt existing rules and the two-axis scorer only where the annotation findings show repeatable errors. Add approved few-shot examples only for measured failure types; keep them out of held-out cases. No new agent framework or database is assumed. | Prior-turn-dependent, contradictory, and postponed-intent examples produce explainable labels. No CareSure fact appears without approved KB support. Existing API shape and model/tool/cost caps remain intact. | 2–4 h |
| 4. Evaluation and release gate | With the repository-required consent for new test code, add offline and model-based multi-turn cases, including out-of-scope, missing facts, false-positive handoffs, false-negative restricted answers, duplicate confirmation, verified/unverified conversion, and sensitivity leakage across all persistence surfaces. Keep source, licence, and split metadata for imported examples. | Report per-field precision/recall or confusion counts, handoff timing, evidence quality, unsupported-fact rate, and cost. Require zero observed restricted-decision and sensitive-leak failures in the agreed safety suite; do not claim statistical proof from a small suite. | 2–3 h plus model-run time |
| 5. Staff-facing explanation | If earlier gates pass, surface the short reason and quoted, privacy-safe evidence for current intent/readiness and handoff in the internal UI. Preserve the low-density inbox/case design; detailed trace stays on the debug route. | A reviewer can explain why priority changed and what needs human action without reading a raw model transcript. | 1–2 h |

The estimates assume the current backend architecture is retained. They exclude recruiting or obtaining consent for real conversations. A small, authorised and redacted local sample is the highest-value missing evidence, but public corpora cannot substitute for it when claiming local accuracy or commercial demand.

## Approval questions before implementation

1. Should a customer-provided payment statement ever advance to `Closed / Active Customer`, or must that wait for a verified payment/application event?
2. In restricted cases, should a pending confirmation still be used while the AI is already prohibited from discussing the restricted substance, or should any category bypass confirmation? The current implementation uses confirmation; changing this is a product decision.
3. What raw transcript, model trace, and case-brief retention is acceptable for this demo, and what must be redacted before persistence?
4. Can the team obtain a small set of consented, anonymised real enquiries or conduct structured role-play with sales staff? Without it, evaluation remains a designed scenario test rather than evidence of market prevalence.
