# SalesPilot

SalesPilot is a hackathon prototype for CareSure, a fictional Singapore health
insurer. It combines a customer chat with a staff console: customers receive
approved product information, while staff see sales signals, opportunity state,
score, priority, agent traces and human-handoff cases.

The model is deliberately not the business authority. Deterministic backend rules
own qualification, scoring, state transitions, escalation and cost limits. An LLM
may extract observations, choose bounded knowledge tools and phrase a response;
offline mode uses rule-based extraction and templates and labels that fact clearly.

## Run locally

Python 3.10+ and a current Node.js are sufficient. The frontend has no packages to
install and no build step.

```powershell
py -3 -m pip install -r requirements.txt
py -3 -m backend --serve --seed
```

In a second terminal:

```powershell
cd frontend
py -3 -m http.server 8123
```

Open:

- Customer chat: http://127.0.0.1:8123/customer/index.html
- Staff console: http://127.0.0.1:8123/admin/index.html#/inbox
- API health: http://127.0.0.1:8000/health

No API key is required. Without one, `/health` reports a degraded provider and the
system answers with deterministic templates. To configure an OpenAI-compatible
provider, run `py -3 -m backend --configure`; secrets are written to the ignored
`.env` file and must never be committed.

## Verify

```powershell
py -3 -m unittest discover -s backend/tests
node --test "frontend/tests/**/*.test.js"
```

Current baseline: 439 backend tests and 283 frontend tests pass.

## Repository map

```text
backend/                 Python service, agent runtime and deterministic kernel
frontend/customer/       Customer-safe chat surface
frontend/admin/          Staff inbox, cases, traces and test harness
backend/knowledge/data/  Approved product knowledge base
runtime/                 Local SQLite data
evals/                   Multi-turn evaluation cases and runner
docs/api/interface-v1.md HTTP contract and visibility boundary
.kiro/specs/             Product requirements, designs and acceptance checklists
```

Important demo limitations: there is no authentication or multi-tenancy, WhatsApp
Cloud API delivery is not implemented, and delivery ticks are client milestones
rather than server read receipts. All premium figures are fictional.

See [backend/README.md](backend/README.md) and [frontend/README.md](frontend/README.md)
for architecture and operating details.
