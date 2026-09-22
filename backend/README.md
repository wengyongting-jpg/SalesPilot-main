# `backend/` — SalesPilot backend, under reconstruction

> ## ⚠ Not usable yet
>
> **This package does not serve HTTP, does not call a model, and does not persist
> anything.** It is a rebuild in progress. There is no working API here.
>
> `py -3 -m backend --serve` will tell you so and exit non-zero. Only `--probe`
> does anything useful today.
>
> **If you need a running SalesPilot backend right now, use the frozen build:**
>
> ```powershell
> py -3 run.py --serve --seed      # salespilot/, on http://127.0.0.1:8000
> ```
>
> That tree still works and its tests still pass. It is frozen and scheduled for
> deletion once this rebuild lands, so do not add to it.

| | |
| --- | --- |
| **Status** | Phases P0–P2 of 8 complete. No HTTP surface, no model access, no storage. |
| **Owner** | Backend track. Read-only for the frontend track. |
| **Plan** | [`docs/backend-plan.md`](../docs/backend-plan.md) — reasoning, target architecture, phase-by-phase acceptance criteria |
| **Wire contract** | [`docs/api/interface-v1.md`](../docs/api/interface-v1.md) — authoritative request/response shapes |
| **Outstanding gaps** | [`docs/backend-contract.md`](../docs/backend-contract.md) — the register, with per-item tests |
| **What changed when** | [`docs/backend-changelog.md`](../docs/backend-changelog.md) |

---

## What works today

```powershell
py -3 -m backend --probe        # report the effective configuration
py -3 -m pytest backend/tests -q
```

101 tests, covering the layering rules, the domain model and the whole deterministic
kernel. Nothing above the kernel exists yet.

## Progress

| Phase | Delivers | Status |
| --- | --- | --- |
| **P0** | Package skeleton; layering rules made executable | **done** |
| **P1** | `domain/` — the single source of truth for every wire string | **done** |
| **P2** | `kernel/` — state machine, two-axis scoring, qualification gate, priority, next best action, HITL, takeover freeze, quick replies | **done** |
| **P3** | `agent/` — the tool-calling loop, extraction and reply as model/offline peers, schemas generated from the enums | next |
| **P4** | `observability/` — agent run records, cost accounting, terminal rendering | |
| **P5** | `storage/` + `services/` — persistence, idempotency, the orchestrator | |
| **P6** | `api/` — the HTTP surface, split by visibility tier | |
| **P7** | Model access, demo, interface freeze | |

Until **P6** there is no endpoint. Until **P3** no model is ever called.

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

Full account with the measurements: [`docs/backend-plan.md`](../docs/backend-plan.md)
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
| `services/` | Use-cases. Owns transactions, idempotency and run records. The only package that writes storage. |
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

## Contributing while this is in flight

- Phases are sequential; each leaves the tree importable and has executable acceptance
  criteria. Do not start one before its predecessor is green.
- Tests first. Tests live in `backend/tests/`, separate from the frozen top-level
  `tests/`.
- Do not add anything to `salespilot/`. It is frozen.
- Do not touch `frontend/**` or `.kiro/specs/**`. Raise the need instead.
