# Backend plan — rebuild to an agentic architecture

| | |
| --- | --- |
| **Owner** | **Backend track. This document is backend-owned.** |
| **Frontend access** | **Read-only. The frontend track may not edit this file.** |
| **Status** | active |
| **Timebox** | 7 days · 2026-09-22 → 2026-09-28, submit 2026-09-29 |
| **Event** | *Show me your agents* |
| **Companions** | `docs/api/interface-v1.md` (shared contract) · `docs/backend-contract.md` (gap register) · `docs/backend-handoff.md` (ownership) · `docs/backend-changelog.md` (gated record) |

If the frontend track believes this plan must change, raise it rather than editing
this file. The reciprocal rule already binds the backend with respect to
`frontend/**` and the frontend specs.

---

## 1. Why rebuild

The existing backend is not badly written. It has one genuinely good design
decision at its centre — **the LLM never makes a business decision** — and that
decision is worth preserving verbatim. What it lacks is not code quality:

**It has no agent.** The pipeline is a fixed twelve-step straight line. The model
is invoked once for extraction and once for phrasing. There is no loop, so the
system cannot decide to look something up, cannot look something up twice, cannot
ask a clarifying question and continue, and cannot chain actions. For an event
named *Show me your agents*, that is a capability gap, not a style preference.

**The model layer and the domain layer have silently drifted.** Verified against
the code on 2026-09-22:

| Drift | Consequence |
| --- | --- |
| The extraction prompt offers the model `"medical_question"`; the domain enum has `"underwriting"` | Extraction returns `Intent.GENERIC` with `restricted=False`. The HITL trigger `det.intent == Intent.UNDERWRITING` can never fire in LLM mode |
| The prompt lists 7 of the 11 signals | `Withdrawal`, `Conversion`, `Negotiation` and `Purchase Preparation` are unreachable in LLM mode |
| The prompt instructs the model to fold negotiation into `Compliance Risk` | The P0-4 fix — negotiation must never be mislabelled as medical/underwriting/compliance — is bypassed in LLM mode |
| `LLMExtractor.extract` catches every exception and falls back to rules without logging | A misconfigured or rate-limited model degrades invisibly. The only trace is the `extraction_source` field |
| Every one of the 80 tests constructs the agent without an LLM client | LLM mode has **zero** test coverage |

The root cause is structural: **the prompt and the domain enums are two
hand-maintained copies of one truth, with nothing binding them.** No framework
fixes that by itself; a framework that derives tool and output schemas from the
enums does.

**The visibility boundary is in the wrong place.** `POST /api/messages` returns
score, priority, signals, state, next best action and case to whoever calls it,
and relies on the customer frontend to discard them. That is not a boundary — the
data reaches the customer's browser. Once model prompts, token counts and costs
exist it becomes untenable. `interface-v1.md` §2 specifies the fix.

**There is almost no observability.** One log line per message. No per-step
timing, no token or cost accounting, no record of what the model actually
returned, no way to see that a step degraded.

## 2. One track

**Decision, 2026-09-22.** `salespilot/` is **frozen** and will be **discarded** once
the rebuild lands. It receives no further changes of any kind — not even the
prompt-drift fix, because a codebase scheduled for deletion is not worth renovating.
`backend/` is the only forward track and the only implementation of
`interface-v1.md` §5.

What this settles:

| Question | Answer |
| --- | --- |
| Dual implementation of interface v1 | No. Once, in `backend/`. |
| Port | `backend` takes `8000`. The frozen build is not run concurrently. |
| The scoring model | Free to redesign. No frozen tests constrain it; see gap register item 13. |
| Fallback demo | The frozen `salespilot/` tree still runs if it is ever needed, but it is not a maintained deliverable. |

`backend/` was created by copying `salespilot/`. Nothing of that copy is
load-bearing; it is a starting point to delete from, not a base to patch. Expect
most files to be replaced rather than edited.

**Target is `interface-v1.md` §5, not a graph runtime.** The distinction that
matters: a genuine tool-calling loop is added *around* the deterministic kernel;
the kernel itself is neither dissolved into a graph nor exposed as tools. State
machine, scoring, priority bands, next-best-action rules and HITL stay plain
Python with no framework dependency, run unconditionally, and stay directly
unit-testable. §3 explains why the kernel cannot be a tool.

**Consequence for the frontend.** `interface-v1.md` §4 is now historical — it
documents the frozen build. The integration target for both adapters is §5.

## 3. Target architecture — the kernel between two model steps

### The kernel is a mandatory, exactly-once step — not a tool the model may choose

The useful framing, arrived at in review: think of the kernel as **one step that
must execute exactly once per message**. That is the right mental model. The
question this section settles is *where that guarantee lives*, because "must
execute exactly once" and "is a tool" are two different implementations of the same
intent with very different failure modes.

An earlier draft said "the agent calls the kernel, the kernel exposed as tools".
That was wrong, and the enforced layering in §4 never matched it: `agent` has no
permission to import `kernel` at all.

Three objections that are sometimes raised against kernel-as-tool **do not
survive** once it is framed as a single mandatory composite call, and they are
recorded here so they are not re-argued:

| Objection | Why it dissolves |
| --- | --- |
| The model could skip it | Forced tool use (`tool_choice: required`) prevents that |
| The model could call it twice | The runtime can cap it at one |
| The model could reorder the internal rules | With **one** composite `decide(observations)` call, the internal order is ordinary code |

A fourth objection — "the model would choose the arguments" — was simply a bad
argument and is withdrawn: the arguments *are* the model's own observations, and
producing observations is exactly its job. It never names the state it prefers.

**What does decide the question, and why the kernel executes in `services`:**

1. **Where the invariant lives.** As a forced tool, "the kernel ran exactly once"
   becomes a property of runtime configuration, framework behaviour and loop
   termination. As a plain call in `services.conversation`, it is a property of a
   line of Python. For a system whose value proposition is auditable decisions,
   structural beats configured. It is also testable with no model present at all.
2. **Symmetry with the offline path — the decisive reason.** In offline mode there
   *is* no model loop. If the kernel lived inside the loop, offline would need a
   different orchestration, producing two decision paths that share no contract —
   which is precisely the structure that caused the prompt drift in §1. With the
   kernel in `services`, offline and online differ only in which extractor and
   which composer are plugged in; the decision path is byte-identical.
3. **Failure modes.** If the provider times out mid-run and the kernel is a tool
   inside that run, *no decision was made*: the message arrived and the profile
   silently did not update. With the kernel outside, extraction degrades to the
   rule-based peer and the kernel still runs. The profile is always current.

**A rule the model can skip is not a rule — and a rule whose execution depends on a
provider staying up is not much better.**

### What the tools actually are

Read-only knowledge access, plus one proposal channel. None of them reach the
kernel.

| Tool | Nature | Why it is safe to expose |
| --- | --- | --- |
| `lookup_product_fact` | read-only | Idempotent, no side effects. A missed call produces a weaker answer, not a corrupted profile |
| `compare_products` | read-only | Enables the multi-hop case: "compare the waiting period of Plus and Family" |
| `list_products` | read-only | Lets the model discover the catalogue instead of it being hardcoded in a prompt |
| `get_conversation_summary` | read-only | Context, not a decision |
| `request_human_handoff` | **proposal** | Writes a `HandoffProposal`; `kernel/hitl.py` reads it as one input among several and decides for itself |

Modelling the handoff as a proposal rather than an action has a second benefit: the
telemetry can show that the model asked for a handover and the kernel declined. If
it opened the case directly, that disagreement would vanish into the outcome.

### One continuous conversation, not two disconnected chats

A second correction from the same review. An earlier diagram showed "extract" and
"compose" as two model steps, which implied two independent chats with no shared
memory. That implication was an artefact of the drawing, not a property of the
design, and it would have been a real defect: the model that words the reply should
remember how it reached its understanding, what it looked up, and what came back.

The two segments **share one message history**. Verified against
`pydantic-ai` 2.46 — the second segment's first message is still the original system
prompt and the customer's own words:

```
--- what the model sees during the composing segment ---
  0. ModelRequest   [SystemPromptPart, UserPromptPart]   original prompt + customer text
  1. ModelResponse  [ToolCallPart]                       a tool it chose itself
  2. ModelRequest   [ToolReturnPart]                     the knowledge that came back
  3. ModelRequest   [UserPromptPart]                     the kernel's verdict, injected
  4. ModelResponse  [TextPart]                           the reply, with all of the above in view
```

So: control is inverted *within* understanding and wording — that part is a real
loop the model drives, with continuous memory across it. The transaction as a whole
is still orchestrated, and the kernel still runs unconditionally between turn 2 and
turn 3 of that same conversation.

```
services.conversation.handle_customer_message()        orchestrator, runs once
   │
   ├─ 1. observing segment          ─┐
   │        model selects read-only   │
   │        tools, reasons, reasons    │   one shared
   │        again                      │   message_history
   │        -> Detection               │   spans the whole
   │           HandoffProposal         │   request
   │           (observations)          │
   │                                   │
   ├─ 2. kernel.decide()   plain Python, mandatory, exactly once, fixed order
   │        takeover -> state_machine -> signals -> scoring
   │        -> priority -> next_best_action -> hitl
   │        -> full verdict          ──> storage + telemetry  (never to the model)
   │        -> safe projection       ──> injected as the next turn
   │                                   │
   ├─ 3. composing segment           ─┘
   │        continues the same conversation, now with the verdict in view
   │
   └─ 4. storage + observability                       persist and account
```

What crosses into the model's context at step 2 is a **customer-safe projection** of
the verdict — "the customer is weighing cost against value; answer with approved
facts and do not push" — never `state="Evaluation & Hesitation"`, never a score,
never a priority band. The full verdict goes to storage and telemetry directly. That
is red line 3 below, and it is what lets continuity and non-disclosure hold at the
same time.

One honest cost: the composing segment re-sends the observing segment's history.
Quantified in §12, along with where that does and does not become dangerous.

| Layer | Responsibility | May the model influence it? |
| --- | --- | --- |
| **Agent shell** | What to look up, what to ask, how to word the reply | Yes — this is its job |
| **Tool surface** | The five read-only / proposal tools above | It chooses which to call |
| **Deterministic kernel** | State transition, score, priority, next best action, HITL escalation | **Never. It is not reachable from `agent`.** |

### Three red lines

1. **The model may propose, never decide.** `request_human_handoff` is a proposal.
   The model cannot set a state, move a score, or open a case.
2. **Every schema is generated from `domain/enums.py`.** Tool signatures and
   structured-output models derive from the enums. A value the domain does not
   accept fails validation and is recorded as a model contract violation — never
   silently downgraded.
3. **The prompt is a visibility boundary too.** `interface-v1.md` §2 defines the
   tiers on response shape, but anything placed in a customer-reply prompt can
   appear in what the customer reads. The frozen build puts internal state and
   signal names straight into that prompt:

   ```python
   # salespilot/response/llm_generator.py
   f"sales signals: {signals}; opportunity state: {opp.state.value}."
   ```

   A model can repeat that back — "I see you are in the Evaluation & Hesitation
   stage." So step 3 receives a **customer-safe instruction derived from the next
   best action**, never the score, the band, the internal state name or the signal
   names. Enforced in `agent/policy.py` and checked in P3.

## 4. Directory design

Nine packages, each with one job. The current layout mixes agent concerns,
detection, response generation and engine rules at the same level; this separates
the three axes that actually differ: **pure data**, **deterministic decisions**,
and **model-facing work**.

```
backend/
├── __init__.py                  # Python version guard
├── __main__.py                  # python -m backend
├── cli.py                       # --serve / --demo / --seed / --probe
├── config.py                    # settings, provider config, feature flags
│
├── domain/                      # pure data. stdlib only. no I/O, no framework.
│   ├── enums.py                 #   THE single source of truth for every wire string
│   ├── message.py               #   Message: id, role, author, generation, text, ts, key
│   ├── opportunity.py           #   Opportunity, ScoreCard, score/state history
│   ├── case.py                  #   HumanCase
│   └── detection.py             #   Detection, RetrievalResult, KnowledgeMatch
│
├── kernel/                      # deterministic business core. imports domain only.
│   ├── state_machine.py
│   ├── scoring.py
│   ├── priority.py
│   ├── next_best_action.py
│   ├── hitl.py
│   ├── takeover.py              #   the freeze / lifecycle-exception rules, extracted
│   ├── qualification.py         #   the three-level gate; the machine may only "hold"
│   └── quick_replies.py         #   interface §5.5
│
├── knowledge/
│   ├── loader.py
│   ├── keyword.py
│   ├── semantic.py
│   └── data/knowledge_base.json
│
├── agent/                       # the ONLY package that may call a model
│   ├── runtime.py               #   agent construction and run
│   ├── policy.py                #   system prompts, guardrails, compliance red lines
│   ├── schema.py                #   structured outputs GENERATED from domain.enums
│   ├── extraction/
│   │   ├── __init__.py          #     Extractor protocol, selection, degradation report
│   │   ├── model_based.py
│   │   └── rules/               #     offline peer implementation, not a fallback hack
│   │       ├── intent.py
│   │       ├── product.py
│   │       └── signals.py
│   ├── reply/
│   │   ├── __init__.py          #     Composer protocol
│   │   ├── model_based.py
│   │   └── template.py          #     offline peer; marks generation="template"
│   └── tools/                   # what the model is allowed to do
│       ├── __init__.py          #     registry; schemas derived from domain.enums
│       ├── knowledge.py
│       ├── opportunity.py       #     read-only conversation summary
│       └── handoff.py           #     proposes escalation; kernel decides
│
├── observability/               # first-class, not an afterthought
│   ├── run.py                   #   AgentRun / RunStep / LlmCall / ToolCall — interface §5.3
│   ├── recorder.py              #   context managers; degradations and violations
│   ├── pricing.py               #   token price table → cost, computed server-side
│   ├── console.py               #   terminal renderer: per-run block, warnings, totals
│   └── logging.py               #   structured logger setup
│
├── providers/
│   ├── base.py                  #   ModelProvider protocol
│   ├── openai_compatible.py     #   any base_url — the organiser gateway path
│   ├── probe.py                 #   startup capability probe and compatibility report
│   └── offline.py               #   no model available; forces the offline path
│
├── storage/
│   ├── base.py
│   ├── memory.py
│   ├── sqlite.py
│   ├── schema.sql
│   └── migrations.py
│
├── services/                    # use-cases. own transactions, idempotency, run records.
│   ├── conversation.py          #   handle_customer_message
│   ├── rep_reply.py             #   interface §5.4
│   ├── cases.py
│   ├── analytics.py
│   └── seeding.py
│
└── api/
    ├── app.py                   # factory, middleware, router wiring
    ├── deps.py
    ├── errors.py
    ├── routes/
    │   ├── customer.py          #   /api/messages, /api/conversations/*
    │   ├── admin.py             #   /api/admin/*
    │   └── system.py            #   /health
    └── schemas/
        ├── customer.py          #   HAS NO SHAPE for sensitive data — interface §2
        ├── admin.py
        └── shared.py
```

### Rules the layout encodes

1. **Import direction is one-way.**
   `domain ← kernel ← services → agent → providers`, and `api → services`.
   `domain` and `kernel` import nothing from the rest of the tree, so they stay
   stdlib-only, offline, and directly unit-testable.
2. **`agent/` is the only package that may import `providers/` or the agent
   framework.** Anywhere else, a model call is a layering violation.
3. **The offline path is a peer, not a fallback branch.**
   `extraction/model_based.py` and `extraction/rules/` implement one protocol; the
   same for `reply/`. This is the structure whose absence caused the prompt drift:
   the two implementations now share a declared contract.
4. **The tier boundary is a type, not a filter.** `api/schemas/customer.py` cannot
   express a score or a state. Leaking becomes impossible rather than discouraged.
5. **`observability/` is imported by `services/` and `agent/`, never by
   `kernel/` or `domain/`.** Business rules stay free of instrumentation.
6. **The kernel receives its inputs; it never reaches out for them.** `scoring.score`
   takes an injected `now`; `hitl.evaluate` takes a `confidence_floor` whose default
   is a kernel constant. Neither reads `config`, and `kernel` has no permission to
   import it. A business rule whose outcome depends on an environment variable the
   module fetched for itself is not reproducible from the stored record — which
   defeats the point of having an auditable core. An operator who wants different
   thresholds passes them in from `services`.
7. **No legacy console.** `backend/` serves no `static/` UI. The two frontends
   under `frontend/` replace it. `salespilot/static/` remains frozen where it is.

## 5. Framework decision

**Pydantic AI (`pydantic-ai-slim[openai]`, 2.46.0).** Verified on this machine
against Python 3.14.2 before committing to it:

| Requirement | Verified |
| --- | --- |
| Structured output typed by a domain enum | `r.output.intent` is a real `Intent` member; the schema is generated from the enum |
| Tool calling | A registered tool was selected and called; `ToolCallPart` / `ToolReturnPart` appear in the message trace |
| Full run trace available for telemetry | `run.all_messages()` yields every request and response part |
| Runs with no network | `TestModel` executes the whole loop offline, tools included |
| Arbitrary OpenAI-compatible endpoint | `OpenAIChatModel` accepts a provider with a custom `base_url` |

Why this one, given a seven-day budget:

- It kills the defect class in §1 by construction. Schemas come from the enums.
- It is a loop and a tool runtime, not a graph engine, which matches "wrap the
  kernel, do not dissolve it".
- `pydantic` is already a transitive dependency via FastAPI, so the marginal
  dependency weight is small.
- `TestModel` makes the agent loop testable with no key and no network — the same
  property that currently makes this project safe to demo.

Rejected alternatives, briefly: a graph runtime buys checkpointing and interrupts
we do not need and would pull the state machine into the framework, losing the one
property that is currently solid. **OpenClaw** solves a different problem — per its
[project site](https://openclaw.ai/) and a [community architecture
write-up](https://gist.github.com/royosherove/971c7b4a350a30ac8a8dad41604a95a0) it
is a self-hosted, continuously running personal-assistant runtime with channel
routing and tool execution on your own infrastructure (description rephrased).
SalesPilot needs an embedded domain agent behind a REST API that both frontends
already target; adopting OpenClaw as the core would invert the product shape and
strand the two finished frontends. It remains interesting as a *separate* demo
shell — for example letting a representative query the case queue from their own
messaging app — which is an add-on, not a foundation.

**Fallback if the framework disappoints.** The seam is `agent/runtime.py`. If the
framework blocks us, a hand-rolled tool-calling loop against
`providers/openai_compatible.py` replaces that one module; `domain`, `kernel`,
`services`, `storage` and `api` are unaffected. Decision checkpoint: end of day 2.

## 6. Model access and the offline requirement

The organiser API is not in hand yet. The plan does not wait for it.

| Mode | Trigger | Behaviour |
| --- | --- | --- |
| `gateway` | organiser base URL and key configured | Normal operation through the OpenAI-compatible path |
| `openai` | own key configured | Same path, different endpoint |
| `offline` | no key, or the probe fails | Rule-based extraction and template replies. The full pipeline still runs |

`providers/probe.py` runs at startup, reports what it found, and prints a
compatibility verdict. If the organiser endpoint turns out not to be
OpenAI-compatible, the adapter seam is `providers/`, and only that package changes.

**Offline must be visible, not silent.** Every agent-side message carries how it
was produced, so the UI can label it and a viewer is never misled about whether
they are reading a model, a template, or a person:

| `role` | `author` | `generation` | Rendered as |
| --- | --- | --- | --- |
| `customer` | `null` | `null` | The customer's own message |
| `business` | `ai` | `llm` | AI reply |
| `business` | `ai` | `template` | AI reply, offline mode — no model was called |
| `business` | `human` | `human` | A human representative |
| `business` | `system` | `template` | Deterministic system notice, e.g. handover |

Three axes, deliberately. `role` answers which side, `author` answers who,
`generation` answers how. `interface-v1.md` §1 records what happens when one field
carries two meanings; this avoids repeating it. Recorded as `interface-v1.md` §5.7.

`role: "agent"` is renamed to `role: "business"` for the same reason: "agent" reads
as "AI agent", so a human representative's message under it contradicts itself. The
value names the party; `author` and `generation` answer the other two questions.
Recorded as `interface-v1.md` §5.8 and gap register item 11. No transitional alias.

## 7. Observability

Two audiences, one record.

**In the terminal**, per agent run: a block listing each step with its kind,
duration and status; each model call with model name, tokens, cost and latency;
each tool call with arguments and result size; and totals. Degradations and model
contract violations print as warnings, not as silence.

```
▶ run ar-91c4  C-1024  customer_message  key=c-8f2a1b40
  0 extraction           llm        820ms  ok      gpt-4o-mini  412+88=500 tok  $0.00021
  1 tool.lookup_fact     tool        12ms  ok      product=plus field=premium
  2 state_transition     rule         1ms  ok      Potential Interest -> Evaluation & Hesitation
  3 scoring              rule         1ms  ok      45 LOW
  4 response_generation  llm        400ms  ok      gpt-4o-mini  298+64=362 tok  $0.00015
  ✔ ok  1240ms  2 llm  1 tool  862 tok  $0.00036
```

```
▶ run ar-91c5  C-1024  customer_message
  0 extraction           llm        512ms  DEGRADED  model returned intent="medical_question",
                                                     not a member of Intent → fell back to rules
  ...
  ⚠ degraded  the reply was produced without a model (generation=template)
```

**In the response**, on the admin tier only: `GET /api/admin/agent-runs` exactly as
specified in `interface-v1.md` §5.3, persisted per message so history is
inspectable rather than only the latest exchange. Cost is computed server-side from
`observability/pricing.py`. `chars` is always reported even when content is
withheld.

**Prompt and raw output content default to ON in development.** `interface-v1.md`
§5.3 item 4 requires the flag; this records which way it points. The event is *Show
me your agents* — showing a judge what the model actually received and returned is
the demonstration, not a debugging luxury. Flag: `SALESPILOT_TELEMETRY_CONTENT`,
default `on`, set to `off` for anything resembling production. The content may
include the customer's own words, which is why the flag exists at all and why it is
never exposed on the customer tier.

**Never on the customer tier.** Under `interface-v1.md` §2 the customer response
has no shape for any of it.

Three failure classes must be distinguishable, because conflating them is the
complaint that motivated this section:

| Class | Example | Surfaced as |
| --- | --- | --- |
| Program error | `TypeError`, DB locked | exception, 5xx, stack trace in the log |
| Model unavailable | no key, timeout, 429 | step `status=degraded`, warning, `generation=template` |
| **Model wrong** | invalid enum, unparsable JSON, ignored instruction | step `status=degraded` with a violation reason naming the offending value |

The third class is the one that is invisible today.

## 8. Mapping to interface v1

| Interface item | Lands in | Phase |
| --- | --- | --- |
| §5.1 tier separation by namespace | `api/routes/`, `api/schemas/` | P6 |
| §5.2 `author` field | `domain/enums.py`, `domain/message.py` | P1 |
| §5.3 agent run telemetry | `observability/`, `api/routes/admin.py` | P4, P6 |
| §5.4 rep reply | `services/rep_reply.py` | P5, P6 |
| §5.5 quick replies | `kernel/quick_replies.py` | P2, P6 |
| §5.6 incremental fetch | `api/routes/customer.py` | P6 |
| §5.7 `generation` provenance (raised here) | `domain/enums.py`, `domain/message.py` | P1 |
| §5.8 `role` rename to `"business"` (raised here) | `domain/enums.py` | P1 |
| §1.1 `customer_message_count` with `turns` as a deprecated alias | `domain/opportunity.py`, both schemas | P1 |
| gap 12 admin incremental read | `api/routes/admin.py` | P6 |
| gap 13 two-axis scoring + qualification gate | `kernel/scoring.py`, `kernel/qualification.py` | P2 |

## 9. Phased plan

"One step to the target" is the goal for the *result*, not for the *method*. A
seven-day rebuild attempted as a single undifferentiated change cannot be reviewed,
and a failure on day five would leave nothing demonstrable. So the work is cut into
seven phases, each of which:

- leaves the tree in a state that **imports and runs**;
- has an **acceptance check that can be executed**, not merely asserted;
- is **reviewable on its own** before the next phase starts.

Phases are sequential because each depends on the previous one. The framework
decision has an explicit abort point in P3.

Notation: `▢` deliverable, `✔` acceptance check.

**Test authorisation, and where tests live.** `AGENTS.md` Rule 2 requires consent
before authoring tests. The owner granted a standing exception **for the duration of
this plan**: within P0 … P7, test-driven development is authorised — tests first,
then the code. The exception is scoped to this plan and does not generalise.

Tests live in `backend/tests/`, maintained independently of the frozen top-level
`tests/` directory. Each phase's `✔` checks are the specification for that phase's
tests; a phase is not finished until its checks are executable rather than walked by
hand.

```powershell
py -3 -m pytest backend/tests -q            # the rebuild
py -3 -m pytest tests -q                    # the frozen build, unchanged
```

### Progress

| Phase | Status | Tests | Notes |
| --- | --- | --- | --- |
| P0 Clear the ground | **Done** 09-22 | 8 | Layering rules became executable. The test itself had a blind spot, found and fixed in P2 |
| P1 `domain/` | **Done** 09-22 | +23 | Impossible message states are now unconstructable rather than merely discouraged |
| P2 `kernel/` | **Done** 09-22 | +70 | Two corrections made during implementation, recorded below |
| P3 Agent shell | Next | | Framework go/no-go at the end of it |
| P4 `observability/` | | | |
| P5 `storage/` + `services/` | | | |
| P6 `api/` tiers | | | |
| P7 Model access, demo, freeze | | | |

`backend/tests`: **101 passed**. `tests` (frozen build): **80 passed**, untouched.

---

### P0 — Clear the ground

▢ Delete from `backend/` everything that will not survive: `static/`, the old
`agent/assistant.py`, `detection/`, `engine/`, `response/`, `dashboard.py`,
`demo.py`. Create the nine-package skeleton from §4 with `__init__.py` files and
module docstrings stating each package's single job and its allowed imports.
▢ `requirements.txt`: add `pydantic-ai-slim[openai]`, pinned.

✔ `python -c "import backend"` succeeds.
✔ A written import-direction rule exists in `backend/__init__.py`'s docstring and
in §4, and `backend/domain/` and `backend/kernel/` contain no import of any other
`backend` package.

**Done, 09-22.** `backend/tests/test_architecture.py` turns the §4 rules into a
build failure rather than advice: it parses every module with `ast`, checks each
package against an allowlist, checks that `domain` and `kernel` need only the
standard library, and checks that the agent framework appears nowhere but `agent/`.
Reading source rather than importing means a violation is reported even in a module
that does not currently import.

One thing that had to be corrected later, recorded because it is the more useful
lesson: **the check had a blind spot.** `from .. import config` puts the target in
the node's `names`, not its `module`, so that form was invisible and the test was
returning a green it had not earned. Fixed during P2, at which point it immediately
caught a real violation — `kernel/hitl.py` reading `config` — which produced rule 6
in §4. A test that guarantees a layering rule is worth less than nothing if it is
silently partial.

---

### P1 — `domain/` as the single source of truth

▢ `domain/enums.py`: `Intent`, `Product`, `OpportunityState`, `Signal`, `Priority`,
`CaseStatus`, plus the three message axes `MessageRole` (`customer` / `business`),
`MessageAuthor` (`ai` / `human` / `system`), `Generation` (`llm` / `template` /
`human`).
▢ `domain/message.py`, `opportunity.py`, `case.py`, `detection.py`. `Message` gains
`id`, `author`, `generation`; `Opportunity` gains `customer_message_count` with
`turns` retained as a deprecated read-only alias.

✔ Enum values are byte-identical to `interface-v1.md` §4.3 for the six states, three
priorities, five products and eleven signals. Checked by a script that compares the
enum values against the literal lists, not by eye.
✔ `role` yields only `customer` and `business`; the string `"agent"` appears nowhere
in `domain/`.
✔ `domain/` imports nothing outside the standard library.

**Done, 09-22.** Enum values are compared against an independent transcription of
`interface-v1.md` §4.3 and §1.2, so a rename fails here rather than reaching a
frontend with no build step to catch it.

Beyond the stated criteria, `Message` rejects the combinations that are not in the
five documented ones, so an impossible message — a human whose words are recorded as
"generated by a template", or a business reply that declines to say whether a model
produced it — cannot be constructed, let alone stored and later shown to somebody as
if it were true. Four named constructors make the five valid states convenient and
the invalid ones awkward.

`turns` is a read-only property rather than a field: the wire contract keeps the
name, and no code inside the backend can use the misleading one to mutate state.

The `"agent"` scan had to be narrowed from raw text to AST string literals, because
the prose in `enums.py` explaining *why* the rename happened was being flagged as a
surviving alias. Comments never enter the AST and a docstring is one constant holding
a whole paragraph, so the check now sees only live literals.

---

### P2 — `kernel/` ported, deterministic, offline

▢ Port `state_machine`, `scoring`, `priority`, `next_best_action`, `hitl`,
`quick_replies`, and extract the takeover freeze rules into `kernel/takeover.py` —
they are currently inline flags threaded through the old god method.
▢ Scoring, redesigned per gap register item 13: a **fit** axis and a **behaviour**
axis instead of one flat number, with a three-level qualification gate the machine
can only push to *held*. Engagement gains recency decay. `product_potential` and
`expansion` move to the fit axis. `priority` keeps its three values and changes only
its derivation. `turns` keeps its own value and meaning.
▢ Scoring takes an injected `now`, so recency decay is testable rather than
wall-clock dependent.

✔ Every P0-1 … P0-4 behaviour from the frozen build is reproduced, verified by
walking the documented scenarios: price concern does not escalate, competitor
mention alone does not escalate, discount request escalates *as negotiation*,
withdrawal strips Purchase and produces a non-sales reply, takeover persists across
messages without duplicate cases, conversion and withdrawal still pass through the
freeze.
✔ `kernel/` imports only `domain/`. No framework, no provider, no I/O.
✔ Escalation reasons for negotiation contain "negotiation" and none of "medical",
"underwriting", "compliance".
✔ Item 13's six criteria hold, in particular: advertising spam does not reach the
sales queue and does not outrank a genuine customer; the machine never disqualifies,
only holds; a held conversation still escalates abuse or a complaint to a person;
recency decay is observable with an injected clock.

**Done, 09-22.** Modules: `state_machine`, `takeover`, `scoring`, `priority`,
`qualification`, `next_best_action`, `hitl`, `quick_replies`.

The redesign's headline result, against the same three conversations that justified
it:

| Conversation | Frozen build | Rebuild |
| --- | --- | --- |
| Advertising spam, no insurance words | 66 MEDIUM, and it opened a human case | held, fit 0, LOW, absent from the queue |
| Advertising spam, insurance words | **96 HIGH** | held, fit 0, LOW, absent from the queue |
| A genuine high-intent customer | 82 HIGH | qualified, fit 83, behaviour 82, HIGH |

The mechanism is worth stating precisely, because it is not "the arithmetic
suppresses spam": **genuineness is a fit question**, so a conversation that is not a
sales enquiry has a fit of zero whatever it does. That single rule is the industry
convention's "fit gates behaviour" applied literally.

**Two corrections made during implementation.**

*Decay had to become multiplicative.* The first version added recency as a
dimension worth ten of a hundred behavioural points, and the result was that a
well-fitting opportunity with forty days of silence still came out HIGH — a decay
that cannot move a band is decoration. Recency now scales the whole behaviour axis
(100% down to a 35% floor), which is what "stale evidence counts for less" actually
means. Fit is not scaled: silence does not make a corporate account less valuable, it
makes the evidence that they are buying weaker. Two assertions were adjusted to the
corrected relationship, and one was added requiring that a long silence be able to
move a strong opportunity out of HIGH.

*The kernel must not read `config`.* See P0's note and §4 rule 6.

**One structural fix carried over from the port.** The frozen build's state machine
imported the signal detector so it could run two text heuristics — cancellation and
postponement — itself, putting extraction logic inside the deterministic core. Both
are observations, so they now arrive on `Detection` and the kernel only reads them.
The takeover freeze, previously a boolean threaded through a two-hundred-line method
and patched again at its end, is now `kernel/takeover.py`, one place, returning a
decision that explains itself.

---

### P3 — Agent shell, and the framework go/no-go

▢ `agent/schema.py`: structured-output models generated from `domain/enums.py`.
▢ `agent/extraction/`: `model_based.py` and `rules/` as two peers behind one
protocol. A value the domain rejects is recorded as a **model contract violation**,
never silently downgraded.
▢ `agent/reply/`: `model_based.py` and `template.py` as two peers; template sets
`generation="template"`.
▢ `agent/tools/`: `lookup_product_fact`, `compare_products`, `list_products`,
`get_conversation_summary`, `request_human_handoff`. Signatures typed from the
enums. `request_human_handoff` only *proposes*; `kernel/hitl.py` decides.
▢ `agent/runtime.py`: the loop.

✔ With `TestModel`, a run completes offline and the trace contains at least one
model-selected tool call.
✔ Feeding the model output `{"intent": "medical_question"}` produces a recorded
violation naming the offending value — the exact defect that is silent in the frozen
build.
✔ The multi-hop case works: "compare the waiting period of Plus and Family" results
in two knowledge lookups in one run.
✔ No tool reaches `kernel`, and `agent` does not import it (§3, enforced by
`test_architecture.py`). `request_human_handoff` produces a `HandoffProposal` and
opens no case.
✔ Red line 3: the customer-reply prompt contains no internal state name, no signal
name, no score and no priority band. Asserted against the assembled prompt text,
not reviewed by eye.
✔ **Go/no-go.** If the framework has blocked any of the above, replace
`agent/runtime.py` with a hand-rolled tool-calling loop over
`providers/openai_compatible.py` and continue. Nothing outside `agent/` changes.
This is the last phase at which the decision is cheap.

---

### P4 — `observability/`, both surfaces

▢ `run.py`, `recorder.py`, `pricing.py`, `console.py`, `logging.py`. The record
shape matches `interface-v1.md` §5.3 field for field.
▢ Terminal renderer per §7, including the warning form for degradations and
violations.
▢ Cost computed server-side from the price table.

✔ A normal run prints one block with per-step kind, duration, status, model, tokens
and cost, and totals that equal the sum of the parts.
✔ Three failure classes are distinguishable in the output: program error, model
unavailable, model wrong (§7).
✔ `tool_call_count` reflects only model-selected calls. Retrieval reports
`kind: "retrieval"` and does not increment it.
✔ `kernel/` and `domain/` contain no import of `observability/`.

---

### P5 — `storage/` and `services/`

▢ `storage/`: `memory.py`, `sqlite.py`, `schema.sql`, with tables for
opportunities, cases, message receipts and **agent runs** persisted per message.
▢ `services/conversation.py`: idempotency on `client_message_id`, persistence, run
recording, the takeover freeze applied through `kernel/takeover.py`.
▢ `services/rep_reply.py`, `cases.py`, `analytics.py`, `seeding.py`.

✔ The five P0-5 idempotency criteria hold: replay returns the stored response
verbatim, `customer_message_count` and the transcript length are unchanged, no new
score-history entry, a different key advances, omitting the key is non-idempotent.
✔ A receipt survives a simulated restart under SQLite.
✔ Agent runs are queryable by `opportunity_id` and by `client_message_id`, with more
than one run retained per conversation.
✔ `services/` is the only package that writes storage.

---

### P6 — `api/`, tier separation

▢ `routes/customer.py`: `POST /api/messages`, `GET|DELETE /api/conversations/{id}`
with `?since=` (§5.1, §5.6).
▢ `routes/admin.py`: `/api/admin/*` — opportunities, cases, dashboard, analytics,
`agent-runs` (§5.3), `rep-reply` (§5.4).
▢ `schemas/customer.py` that **cannot express** score, priority, signals, state,
next best action, case internals, retrieval confidence or telemetry.
▢ `quick_replies` on the customer response (§5.5).

✔ Every field in the "no" column of `interface-v1.md` §2 is absent from the customer
response. Verified by asserting against the response keys, not by reading the code.
✔ `rep-reply` returns 409 when the opportunity is not under takeover, and appends
nothing.
✔ A rep reply serialises as `role: "business"`, `author: "human"`,
`generation: "human"`.
✔ No response anywhere contains `"role": "agent"`.

---

### P7 — Model access, demo, freeze

▢ `providers/probe.py` wired into startup, printing a compatibility verdict.
▢ Organiser gateway integrated if available; otherwise the documented offline path
with the adapter seam noted.
▢ Walk `interface-v1.md` §6 degradation matrix end to end.
▢ Mark `interface-v1.md` `Status: frozen`; request the changelog entry.

✔ With no key configured, a full conversation completes, every business message
reports `generation: "template"`, and each run reports `status: "degraded"`.
✔ With a key configured, the same conversation reports `generation: "llm"` and
`status: "ok"`.
✔ Both frontends run against `backend/` on port 8000 with their real adapters.

---

### Ordering against the calendar

| Day | Planned | Actual |
| --- | --- | --- |
| 09-22 | P0, P1 | **P0, P1, P2 — half a day ahead** |
| 09-23 | P2, P3 (go/no-go by end of day) | P3 |
| 09-24 | P4 | |
| 09-25 | P5 | |
| 09-26 | P6 | |
| 09-27 | P7 | |
| 09-28 | Buffer, rehearsal. Submit 09-29. | |

If a phase slips, the ones that follow slip with it; phases are not reordered,
because each depends on its predecessor. The buffer day absorbs one slip. The half
day gained in P2 is the first candidate for converting the acceptance checks that are
still walked by hand into further tests, per §11.

## 10. Out of scope

- Authentication. Unchanged decision, recorded in `interface-v1.md` §2 and
  `.kiro/steering/product.md`. No fake login.
- WebSocket or server-sent events. Polling is sufficient.
- A graph or multi-agent runtime.
- Any change under `frontend/**`, `.kiro/specs/**`, or `salespilot/static/**`.
- Porting the existing 80 tests on a schedule. Test strategy for `backend/` is
  deferred by explicit decision. The phase acceptance checks in §9 are executable
  and cover the same behaviours; `TestModel` makes converting them into a suite cheap
  once the shape is settled.
- Any further change to `salespilot/`. It is frozen and will be deleted.

## 11. Risks

| Risk | Mitigation |
| --- | --- |
| Token cost growing quadratically | Three quadratic paths identified and guarded — §12 |
| Organiser API late, or not OpenAI-compatible | Offline mode is a first-class peer, not a stub. Adapter seam confined to `providers/` |
| Framework does not fit | Go/no-go at the end of P3; `agent/runtime.py` is the only module to replace |
| `backend/` unfinished at the deadline | Phases are ordered so that the tree imports and runs after every one of them. The frozen `salespilot/` tree also still runs, though it is no longer maintained |
| Rebuilding without tests reintroduces fixed bugs | **This is the largest risk.** P0-1 … P0-4 are behaviours, not code, and the only executable record of them is a suite that is being frozen. Mitigation: their scenarios are written out as explicit acceptance checks in P2 and P5 and are walked before each phase closes. If a phase finishes early, converting those checks into `tests/backend/` is the first thing to spend the time on |
| Scoring change makes demo numbers move | Intentional and approved. The five dimensions and weights are unchanged, so the demo's *shape* (who is HIGH, who needs follow-up) should hold; the absolute numbers will differ from the frozen build and that is expected |

## 12. Memory and cost model

### 12.1 Three tiers of memory

| Tier | What it is | Lifetime | Size | Written by |
| --- | --- | --- | --- | --- |
| **Working** | The shared `message_history` within one request: observe → tools → verdict → compose | One request | Bounded by the tool-call cap | Model and framework |
| **Short-term** | The most recent `W` turns of transcript, re-sent on each request | The conversation | **Fixed at `W`** | Accumulated transcript |
| **Long-term** | The **opportunity profile** | Permanent, survives restarts | **Constant, independent of conversation length** | **The kernel** (with two exceptions below) |

Long-term memory is not a prose summary. It is structured fields: `state`,
`signals`, `signal_history`, `main_concern`, `expansion`, the three risk flags, the
`best_intent` high-water mark, and the score and state histories.

This tier is the real differentiator. Most agent demos carry only a rolling
transcript window, so they forget: at turn 300 they no longer know the customer
mentioned a competitor at turn 4. Here they still do, because `signal_history`
holds `Competitive` and `best_intent` holds the strongest intent ever observed. It
is also why the short-term window can stay small — what carries the sales context
does not live in the transcript.

**The safety property worth naming: long-term memory is written by the kernel, not
by the model.** The model contributes typed observations; the kernel decides what
enters the profile. A bad model turn therefore cannot poison long-term memory — at
worst it makes one turn's observations wrong, and the profile's evolution rules stay
auditable code. This differs materially from the common pattern of having the model
write its own rolling summary and feeding it back, where an error compounds.

**Two exceptions and one gap, stated rather than hidden:**

1. **`main_concern` and `concerns` are model-authored free text** — the only part of
   long-term memory the model writes directly. They reach the HITL case summary and
   may be re-injected into a later prompt, which is a **prompt-injection path**: a
   customer writes "ignore the previous instructions and …", it is extracted as a
   concern, and it returns inside the next turn's context. Guards: length-capped,
   placed only in a clearly delimited data section and never in a system-prompt
   position, and rendered as untrusted text on the admin surface.
2. **No summarisation tier.** Between `W` turns of verbatim transcript and the
   profile there is a gap: a specific detail from turn 12 is lost. Options
   considered were (a) accept it, since the profile carries what selling needs and
   `main_concern` is already a one-slot summary; (b) a rolling model-written
   summary; (c) semantic retrieval over the stored transcript. **(a) for now.** (b)
   is explicitly rejected because it would make the model the author of long-term
   memory and forfeit the property above; if this gap needs closing, (c) is the
   direction, because retrieval reads rather than rewrites.

### 12.2 Cost per message

Assumptions, so the arithmetic can be re-run with different ones: observing system
prompt 400 tokens, 40 per transcript message, `W` = 6, profile summary 180, current
message 30, each tool round trip 40 out plus 120 in, verdict projection 150,
structured output 120, reply 200. Prices at the `gpt-4o-mini` order of magnitude,
$0.15 and $0.60 per million input and output tokens.

| Tool calls `k` | Model requests | Input tokens | Output tokens | Cost |
| --- | --- | --- | --- | --- |
| 0 | 2 | 1,970 | 320 | $0.00049 |
| 1 | 3 | 3,140 | 360 | $0.00069 |
| **2 (typical)** | **4** | **4,470** | **400** | **$0.00091** |
| 3 | 5 | 5,960 | 440 | $0.00116 |
| 6 (cap) | 8 | 11,390 | 560 | $0.00204 |

A full demo — three customers, six turns each, `k` = 2 — comes to roughly 80,000
input and 7,000 output tokens, about **$0.016**.

There is no third or fourth segment. One customer message is always one observing
segment containing at most `k` tool round trips, plus one composing segment. Nothing
in the design lets the number of segments grow with the conversation.

### 12.3 Three quadratic paths, and the guard for each

**Runaway tool loop — quadratic in `k`.** Each step re-sends the accumulated
history, so cost is O(k²): `k` rising from 2 to 50 is 25× the calls but 57× the
cost, 256,470 input tokens in a single message.

Guard: the framework enforces `tool_calls_limit`, `request_limit` and `cost_limit`,
raising `UsageLimitExceeded`. With `count_tokens_before_request` enabled, an
over-limit request is stopped **before** it is sent, so a runaway costs nothing.

**Unbounded short-term window — quadratic in conversation length, and the most
insidious of the three.**

| Turns `N` | Bounded window (linear) | Unbounded (quadratic) | Ratio |
| --- | --- | --- | --- |
| 10 | 44,700 | 43,900 | **1.0×** |
| 50 | 223,500 | 379,500 | 1.7× |
| 100 | 447,000 | 1,159,000 | 2.6× |
| 300 | 1,341,000 | 8,277,000 | **6.2×** |

Note the first row: at ten turns the unbounded version is marginally *cheaper*. It
looks harmless — better, even — in any short test, and only bites in long
conversations, with a ratio that grows without bound.

Guard: `W` is not merely a constant but a **tested invariant**. The assembled prompt
must have an upper bound regardless of transcript length, asserted in P3.

**Admin payload — linear per poll, therefore quadratic per session.**
`GET /api/opportunities/{id}` returns the complete `messages`, `score_history` and
`state_history`, all of which grow with `N`, and the console polls it. Stored
telemetry compounds it: at `k` = 2 a run holds roughly 18 KB of prompt and output
text, so a thousand messages is around 18 MB in SQLite.

Guard: `TELEMETRY_CONTENT_MAX_CHARS` caps stored content per field, plus a retention
policy. And a gap to close: `interface-v1.md` §5.6 proposes an incremental cursor
for the **customer** surface only, while the admin surface is the one that polls the
full profile and carries the most fields. Raised as gap register item 12 —
`?since=` on the admin conversation read, plus a bound on the history arrays.

### 12.4 Status

**This section is a first pass and there is room to improve it.** It was written to
answer two specific questions — what the memory tiers are, and whether cost can
explode — well enough to proceed safely. The deliberate deferrals are the
summarisation tier in §12.1, the retention policy in §12.3, and any measurement
against a real provider rather than these estimates. Revisit once the rebuild is
functionally complete; none of the deferrals change the architecture, only its
tuning.
