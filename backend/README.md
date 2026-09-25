# `backend/` — SalesPilot backend

> ## The API and both frontend integration paths are operational for the demo.
>
> ```powershell
> py -3 -m backend --serve --seed      # http://127.0.0.1:8000
> ```
>
> Both surfaces are live and both frontends can integrate against them. Everything
> runs in **offline mode by default**: the pipeline completes on the rule-based and
> template peers, and every reply is marked `generation: "template"` so nothing is
> mistaken for model output. `/health` reports `degraded: true` while that is the case.
>
> To check the configured provider without a full conversation test (a configured
> provider may receive a reachability request):
>
> ```powershell
> py -3 -m backend --probe
> ```
>
> The historical interface v1 contract is frozen:
> [`interface-v1.md`](../docs/v0.0/api/interface-v1.md). Verify current behavior
> against the implementation and tests; the archive is not a current readiness claim.
>
> The provider boundary is OpenAI-compatible. Offline mode, the direct OpenAI path
> and the organiser-gateway configuration all resolve through the same model factory.

| | |
| --- | --- |
| **Status** | Demo surfaces operate; SQLite persistence and evaluation repair are planned, not complete. |
| **Current plan** | [`persistence-repair-plan.md`](../docs/v1.0/persistence-repair-plan.md) |
| **Historical design** | [`backend-plan.md`](../docs/v0.0/backend/backend-plan.md) and [`interface-v1.md`](../docs/v0.0/api/interface-v1.md) |

---

## What works today

```powershell
$env:SALESPILOT_LLM = 'offline' # prevents a local .env from enabling model calls
py -3 -m backend --probe        # effective offline configuration
py -3 -m backend --demo         # the whole pipeline in the terminal, no server
py -3 -m backend --serve --seed # the API on http://127.0.0.1:8000
py -3 -m unittest discover -s backend/tests
```

Remove the temporary override with `Remove-Item Env:SALESPILOT_LLM` before using
the same terminal to test a configured LLM provider.

The backend suite covers the deterministic kernel, agent shell, repositories,
orchestrator, HTTP tiers, and provider resolution. Keep the provider in offline
mode when running it to avoid paid model calls from a local `.env`. Do not infer
current readiness from an older
test count or archived phase checklist.

`--demo` is the one to reach for when the question is *what did the agent actually
do*. It prints, for every turn, the detected intent and signals, the state transition,
the score decomposed along both axes, the qualification verdict, the priority, the next
best action, each tool the model chose to call, and the run's token count and cost. The
two web surfaces show the customer's side and the sales queue; neither shows what
happened in between.

## Historical rebuild phases

| Phase | Delivers | Status |
| --- | --- | --- |
| **P0** | Package skeleton; layering rules made executable | **done** |
| **P1** | `domain/` — the single source of truth for every wire string | **done** |
| **P2** | `kernel/` — state machine, two-axis scoring, qualification gate, priority, next best action, HITL, takeover freeze, quick replies | **done** |
| **P3** | `agent/` — the tool-calling loop, extraction and reply as model/offline peers, schemas generated from the enums | **done** |
| **P4** | `observability/` — agent run records, cost accounting, terminal rendering | **done** |
| **P5** | `storage/` + `services/` — persistence, idempotency, the orchestrator | **done** |
| **P6** | `api/` — the HTTP surface, split by visibility tier | **done** |
| **P7** | Model access, API testing, `--demo`, interface freeze | **done** |

These are records of the earlier rebuild, not a claim that persistence repair is
finished. With no model configured the pipeline runs on the
rule-based and template peers, and every reply is marked `generation: "template"`.

## Why a rebuild rather than a refactor

The original backend had one genuinely good design decision at its centre — the model
never makes a business decision — and that is preserved verbatim. What it lacked was
not code quality:

- **No agent.** A fixed twelve-step straight line with one extraction call and one
  phrasing call. No loop, so it could not decide to look something up, look something
  up twice, or ask a clarifying question and continue.
- **The model layer and the domain layer had silently drifted.** The extraction prompt
  offered the model enum values the domain did not accept, which disabled three
  escalation triggers whenever a model was configured — with no error and no log line.
  Nothing in the code prevented it, so it happened.
- **The visibility boundary was in the wrong place.** Score, priority, signals and
  state were returned to whoever called the customer endpoint, relying on the customer
  frontend to discard them. That is not a boundary.
- **Almost no observability.** One log line per message. No per-step timing, no token
  or cost accounting, no way to see that a step had degraded.

Full account with the measurements: [`docs/v0.0/backend/backend-plan.md`](../docs/v0.0/backend/backend-plan.md)
§1.

## Layout

Nine packages, each with one job, and a one-way import direction that is enforced by
a test rather than by convention:

```
domain  <-  kernel  <-  services  ->  agent  ->  providers
                          |             |
                       storage     observability
                          ^
                         api
```

| Package | Job |
| --- | --- |
| `domain/` | Pure data. The single source of truth for every wire string. Standard library only. |
| `kernel/` | Deterministic business core: state, score, priority, next best action, HITL. Imports only `domain`. Never instrumented. |
| `knowledge/` | The product knowledge base and its retrievers. |
| `agent/` | The agentic shell. **The only package permitted to call a model.** |
| `observability/` | Agent run records, cost, terminal rendering. Never imported by `domain` or `kernel`. |
| `providers/` | Model transports, including an offline provider that forces the deterministic path. |
| `storage/` | Repositories: in-memory and SQLite. |
| `services/` | Use-cases and orchestration of idempotency and run records. Atomic SQLite writes remain a planned repair. |
| `api/` | The HTTP surface, split by visibility tier. |

`backend/tests/test_architecture.py` fails the build on a layering violation, on
`domain` or `kernel` acquiring a third-party dependency, and on the agent framework
appearing outside `agent/`.

## The two rules that shape everything here

**1. The model may propose, never decide.** Every business decision — state, score,
priority, next best action, escalation — is made in `kernel`, which `agent` has no
permission to import. The kernel is a mandatory, exactly-once step executed by
`services`, not a tool the model can choose to skip, call twice, or reorder. A rule
the model can skip is not a rule.

**2. Every schema the model sees is generated from `domain/enums.py`.** A value the
domain does not accept fails validation and is recorded as a model contract violation.
It is never silently downgraded — which is exactly what used to happen.

## Contributing

- Keep business decisions in `kernel/`; model output remains advisory.
- Keep visibility tiers explicit: customer projections must never contain sales
  intelligence.
- Run the backend and frontend suites after changing a shared wire shape.
