# SalesPilot

> SalesPilot turns customer conversations into structured sales opportunities.

SalesPilot is an AI sales assistant for **CareSure Health Insurance** (fictional
insurer). It does not simply answer customer questions — it continuously
analyses every message in a WhatsApp-style conversation, detects sales signals,
tracks the customer's position in the buying journey, scores the opportunity
value, determines priority, recommends the next best action, and escalates to
a human sales representative when needed.

## Problem

Sales teams receive large volumes of repetitive customer enquiries through
messaging channels. Manually triaging these conversations to identify and
prioritise valuable sales opportunities is slow, inconsistent, and does not
scale. Reps cannot tell at a glance who needs attention now, why, or what to do
next.

## Solution

SalesPilot converts conversations into structured sales opportunities. Each
customer message flows through a deterministic pipeline that updates the
opportunity profile in real time, so sales reps always see the current state,
signals, score, priority, and recommended action for every customer.

## Innovation

1. **Dynamic Opportunity Intelligence** — A state machine tracks each customer
   through six buying-journey states (Cold Lead → Potential Interest →
   Evaluation & Hesitation → High Intent → Closed/Active → Dormant/Lost).
   State transitions are driven by defined conditions, not by individual
   signals.
   
2. **Sales Signal Detection** — Every message is analysed for observable
   sales, risk, and lifecycle signals, including Purchase, Hesitation,
   Competitive, Expansion, Withdrawal, Conversion, Negotiation, Human
   Intervention, and Compliance Risk. Signals accumulate on the opportunity
   profile and feed into scoring and next-best-action logic — but they never
   automatically change the state.

3. **Opportunity Value Scoring** — A unified 100-point scoring system
   (Purchase Intent 30 + Readiness 20 + Product Potential 20 + Expansion 15 +
   Engagement 15) produces a sales-priority score. Risk flags (competitive,
   compliance) never add points — they drive escalation instead.

4. **AI-to-Human Handoff** — Deterministic HITL rules trigger human takeover
   for personalised underwriting, claims, custom quotations, corporate
   negotiation, complaints, explicit human requests, and high-value
   competitive-risk opportunities. When human handling is active, the AI
   stops making autonomous customer-facing sales decisions.

## Core Workflow

```
Customer Message
      ↓
Conversation History
      ↓
Intent & Context Understanding
      ↓
Opportunity State Detection
      ↓
Sales Signal Detection
      ↓
Update Opportunity Profile
      ↓
Opportunity Value Score
      ↓
Priority
      ↓
Next Best Action
      ↓
Compliance / Permission Check
      ↓
Answer / Nurture / Follow-up / Human Handoff
      ↓
Save Decision + Score History
      ↓
Next Customer Message  ↺
```

## Technology

| Layer | Technology |
| --- | --- |
| LLM | Pluggable provider interface; offline stub by default, OpenAI-compatible adapter included |
| RAG | Rule-based retriever (default) + hybrid semantic retriever (local embeddings + vector store) |
| Decision Engine | Deterministic state machine, scoring, priority, next-best-action, HITL rules |
| State Machine | Six-state opportunity lifecycle with condition-based transitions |
| FastAPI | REST API with 8 endpoints; serves the web frontend at `/` |
| Database | SQLite (opportunities, cases, score history, state history, messages) |
| Frontend | WhatsApp-style chat + sales intelligence panel + dashboard + customer view (served by FastAPI) |
| AWS deployment | Container-ready; deploy to AWS via ECS/Lambda behind an ALB |

> RAG and LLM support the pipeline by providing grounded product answers and
> conversation context. They are **not** the primary innovation — the core
> intelligence is sales opportunity understanding.

---

## Quick Start

> **Requires Python 3.10 or newer.** SalesPilot uses modern `X | None` type
> syntax, so it will not run on Python 3.9 or older. If you start it with an
> older interpreter, `run.py` stops immediately with a clear message telling
> you to use Python 3.11 (or any 3.10+). Check your version with
> `python3 --version`.

Requirements: Python 3.10+ (developed on Python 3.14 using the `py` launcher).

```powershell
cd D:\SalesPilot

# Install dependencies (fastapi, uvicorn, httpx, pytest)
py -3 -m pip install -r requirements.txt

# Start the API server with demo data + web UI
py -3 run.py --serve --seed
#   Open http://127.0.0.1:8000          → SalesPilot web UI
#   Open http://127.0.0.1:8000/docs      → Interactive API docs

# Scripted demo (no install needed)
py -3 run.py --demo

# Interactive CLI chat
py -3 run.py
#   In-chat commands: /dashboard  /customer  /cases  /reset  /help  /quit

# Run the tests
py -3 -m pytest tests/ -v
```

## Architecture

```
                     ┌──────────────────────────────────┐
  Web UI / CLI ─────▶│  FastAPI REST + Static file layer │  api/, cli.py
                     └──────────────┬───────────────────┘
                                    │ AgentResult
                     ┌──────────────▼───────────────────┐
                     │       Agent workflow (12 steps)   │  agent/assistant.py
                     │ detect → state → signals → profile│
                     │ → RAG → score → NBA → compliance  │
                     │ → response → save history         │
                     └───┬───────┬───────┬───────────────┘
          detection/     engine/  knowledge/  response/
          (rules +       state,    retriever   generator
           context)      scoring,  (rule or    (template or
                          decision, semantic)   LLM, safe
                          HITL                  fallback)
                                    │
                     ┌──────────────▼───────────────────┐
                     │ Provider abstraction layer        │  providers/
                     │ LLMClient · Embedder · VectorStore│
                     │ (offline stubs / hashing /        │
                     │  in-memory; OpenAI-compat adapter)│
                     └──────────────┬───────────────────┘
                                    │ BaseRepository
                     ┌──────────────▼───────────────────┐
                     │ In-memory Repository /            │  storage/
                     │ SQLite (opportunities, cases,      │  + analytics/
                     │ score history, state history)     │
                     └──────────────────────────────────┘
```

## Project Structure

```
SalesPilot/
├── run.py                          # Entry point
├── requirements.txt                # fastapi, uvicorn, httpx, pytest
├── data/knowledge_base.json        # Structured KB for four CareSure products
├── logs/                           # Auto-created at runtime
├── runtime/                        # Auto-created: SQLite database location
├── salespilot/
│   ├── models.py                   # Enums, Opportunity, NextBestAction, ScoreCard
│   ├── config.py                   # Paths, thresholds, provider env settings
│   ├── logging_utils.py            # Logging setup
│   ├── detection/                  # Intent, product, signal detectors (with context)
│   ├── knowledge/
│   │   ├── retriever.py            # Rule retrieval with confidence score
│   │   └── semantic.py             # Hybrid semantic retriever
│   ├── engine/
│   │   ├── state.py                # 6-state opportunity state machine
│   │   ├── scoring.py              # 100-point Opportunity Value Score
│   │   ├── decision.py             # Next best action (structured result)
│   │   └── hitl.py                 # HITL escalation rules and case creation
│   ├── response/
│   │   ├── generator.py            # Grounded template generator (nurture/answer/follow-up)
│   │   └── llm_generator.py        # LLM generator with deterministic fallback
│   ├── providers/                  # Pluggable LLM / embedder / vector store
│   ├── storage/
│   │   ├── base.py                 # BaseRepository interface
│   │   ├── repository.py           # In-memory repository
│   │   └── sqlite_repo.py          # SQLite repository
│   ├── analytics/metrics.py        # Sales analytics (FR-15)
│   ├── agent/assistant.py          # 12-step workflow orchestration
│   ├── api/                        # FastAPI service + Pydantic schemas + static serving
│   ├── static/                     # Web frontend (HTML/CSS/JS)
│   ├── dashboard.py                # Text dashboard / customer view
│   ├── demo.py                     # Scripted Sarah / Michael / ABC conversations
│   ├── seed.py                     # Idempotent demo-data seeding
│   └── cli.py                      # CLI flags
└── tests/                          # 31 test cases across all layers
```

## REST API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/` | SalesPilot web UI (chat + dashboard + customer view) |
| GET | `/health` | Liveness, opportunity and open-case counts |
| POST | `/api/messages` | Process one customer message; returns reply, opportunity, score, NBA, case |
| GET | `/api/opportunities` | List all opportunity profiles |
| GET | `/api/opportunities/{id}` | One opportunity profile with score and state history |
| GET | `/api/cases` | List HITL cases |
| GET | `/api/dashboard` | Dashboard with structured queue items |
| GET | `/api/analytics` | Sales analytics (funnel, priority mix, signals, conversion rate) |
| POST | `/api/seed` | Seed demo data (idempotent) |

Examples:

```bash
curl -X POST http://127.0.0.1:8000/api/messages \
  -H "Content-Type: application/json" \
  -d '{"customer_id":"C-2001","customer_name":"Sam","text":"How much does CareSure Plus cost?"}'

curl http://127.0.0.1:8000/api/analytics
```

## Configuration

Environment variables (all optional — defaults are fully offline):

| Variable | Default | Effect |
| --- | --- | --- |
| `SALESPILOT_LLM` | `stub` | `stub` (offline) or `openai` |
| `SALESPILOT_LLM_MODEL` | `gpt-4o-mini` | Chat model name |
| `SALESPILOT_LLM_BASE_URL` | — | Base URL for compatible gateways |
| `SALESPILOT_LLM_API_KEY` / `OPENAI_API_KEY` | — | API key |
| `SALESPILOT_HOST` / `SALESPILOT_PORT` | `127.0.0.1` / `8000` | API bind address |

CLI flags: `--demo`, `--serve`, `--seed`, `--db PATH`, `--semantic`, `--llm`,
`--host`, `--port`.

## Scoring

Opportunity Value Score (100 points):

| Dimension | Max | Scoring |
| --- | --- | --- |
| Purchase Intent | 30 | 0–5 generic / 6–15 interest / 16–24 evaluating / 25–30 explicit |
| Purchase Readiness | 20 | 0–5 exploring / 6–10 comparing / 11–16 application docs / 17–20 ready |
| Product Potential | 20 | Essential 5 / Family 10 / Plus 15 / Corporate 20 |
| Expansion Opportunity | 15 | None 0 / Possible 5 / Family 8–10 / Multiple 11–15 |
| Engagement & Urgency | 15 | Low 0–4 / Some 5–8 / Active 9–12 / Time-sensitive 13–15 |

Priority bands: **High ≥ 80**, **Medium ≥ 50**, **Low < 50**.

Competitive Risk, Compliance Risk, and Human Request never add points to the
score — they drive Next Best Action and HITL escalation instead.

## Tests

```powershell
py -3 -m pytest tests/ -v
```

Coverage: classifiers with context, state machine transitions, scoring
dimensions, HITL triggers, end-to-end 4-message journey, SQLite round-trip,
semantic RAG, provider fallback, analytics, and REST API via TestClient.

## Notes

- All premium figures are fictional indicative rates for demo purposes only.
- The Opportunity Value Score supports sales prioritisation only. It never
  determines eligibility, pricing, underwriting, or claims decisions.
- The AI never autonomously performs underwriting, medical decisions, claim
  approvals, custom quotations, corporate pricing, or eligibility decisions.
