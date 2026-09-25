# SalesPilot

SalesPilot is a hackathon prototype for CareSure, a fictional Singapore health
insurer. It combines a customer chat with a staff console: customers receive
approved product information, while staff see sales signals, opportunity state,
score, priority, agent traces and human-handoff cases.

The model is deliberately not the business authority. Deterministic backend rules
own qualification, scoring, state transitions, escalation and cost limits. An LLM
may extract observations and select approved knowledge facts for a response;
offline mode uses rule-based extraction and templates and labels that fact clearly.

## Run locally

Python 3.10+ and a current Node.js are sufficient. The frontend has no packages to
install and no build step.

### Quick Start (Zero Cost)

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

### Configuration

**Default Mode: Offline (Zero Cost)**

By default, the backend runs in offline mode using rule-based extraction and template
replies. Every message is marked `generation: "template"` and `/health` reports
`degraded: true`.

To inspect the effective configuration or run the backend tests in offline mode:

```powershell
$env:SALESPILOT_LLM = 'offline'
py -3 -m backend --probe
py -3 -m unittest discover -s backend/tests
```

If you use the same PowerShell session for LLM mode later, remove that override
with `Remove-Item Env:SALESPILOT_LLM` first; otherwise it takes precedence over
the value in `.env`.

**Optional: Enable LLM Mode (Costs Money)**

⚠️ **Warning:** Enabling LLM mode will make API calls and incur charges.

1. Copy the example configuration:
   ```powershell
   Copy-Item .env.example .env
   ```

2. Edit `.env` and set:
   ```bash
   SALESPILOT_LLM=gateway              # or 'openai'
   SALESPILOT_LLM_API_KEY=your-api-key
   SALESPILOT_LLM_MODEL=your-model-name
   SALESPILOT_LLM_BASE_URL=https://your-endpoint/v1
   ```

3. Verify configuration:
   ```powershell
   py -3 -m backend --probe
   ```

   In LLM mode, `--probe` checks provider reachability and may make a network
   request. Run the test suite with `SALESPILOT_LLM=offline` to prevent an
   existing local `.env` from enabling paid model calls during verification.

**Cost Limits:**
- Default: $0.03 per message (configurable via `SALESPILOT_LLM_COST_LIMIT_USD`)
- Tool calls: max 3 per message
- Token limit: 12,000 per message

See [.env.example](.env.example) for all available configuration options.

## Verify

```powershell
$env:SALESPILOT_LLM = 'offline'
py -3 -m unittest discover -s backend/tests
node --test "frontend/tests/**/*.test.js"
```

These commands run the maintained suites. The archived documents contain older
test counts that should not be used as a current baseline. The known SQLite
handoff-persistence gap is described in the
[v1.0 repair plan](docs/v1.0/persistence-repair-plan.md).

## Repository map

```text
backend/                 Python service, agent runtime and deterministic kernel
frontend/customer/       Customer-safe chat surface
frontend/admin/          Staff inbox, cases, traces and test harness
backend/knowledge/data/  Approved product knowledge base
runtime/                 Local SQLite data
evals/                   Portable evaluation cases and runner
docs/v1.0/               Current work and review plans
docs/v0.0/               Historical contracts, Kiro-era specs and delivery records
```

Important demo limitations: there is no authentication or multi-tenancy, WhatsApp
Cloud API delivery is not implemented, and delivery ticks are client milestones
rather than server read receipts. All premium figures are fictional.

See [backend/README.md](backend/README.md) and [frontend/README.md](frontend/README.md)
for current architecture and operating details, and [docs/README.md](docs/README.md)
for the document map. Historical API contracts are preserved under `docs/v0.0/api/`;
verify current behavior against the implementation and tests.
