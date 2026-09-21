---
inclusion: always
---

# SalesPilot — technology and repository structure

## Backend is read-only for frontend work

Frontend and backend are developed separately. When working on a frontend task:

- **Do not modify anything under `salespilot/`, `tests/`, `data/`, `run.py`, or
  `requirements.txt`.** Read them freely to understand the API contract.
- If a frontend requirement cannot be met with today's API, **do not patch the
  backend**. Record the required change in `docs/backend-contract.md` (what is
  needed, how to test it, how to accept it) and make the frontend degrade
  gracefully so it is never blocked.
- The legacy console in `salespilot/static/` is frozen. Do not extend it.

## Backend, for reference only

Python 3.10+ (developed on 3.14 via the `py` launcher). Stdlib-only decision
engine; FastAPI + Uvicorn for the HTTP layer; SQLite or in-memory repository.

```powershell
py -3 -m pip install -r requirements.txt
py -3 run.py --serve --seed          # API + legacy console on http://127.0.0.1:8000
py -3 run.py --demo                  # scripted demo, no server
py -3 -m pytest tests/ -v            # backend test suite
```

Two distinct APIs exist. Do not conflate them:

- **Provider API** — the OpenAI-compatible endpoint the backend calls to reach an
  LLM (`salespilot/providers/llm.py`). Internal to the backend. The frontend
  never sees it and must never reference it.
- **Backend REST API** — `/api/*` served by `salespilot/api/app.py`. This is the
  frontend's only integration surface. Documented in `docs/backend-contract.md`.

## Frontend stack

Vanilla **HTML + CSS + JavaScript (ES modules)**. No build step, no bundler, no
npm dependencies, no framework.

Rationale: both frontends are demo-scoped supporting surfaces, not the core
innovation. A zero-dependency setup can be opened directly in a browser or served
as static files, which removes install and build failure modes during a live
demo. There is no open-source WhatsApp component library worth adopting — the
official design system is not public, and third-party recreations carry trademark
and proprietary-font risk.

Constraints that follow from this choice:

- No TypeScript, no JSX, no Sass. Plain `.js`, `.css`, `.html`.
- No CDN `<script>` tags. Everything ships from the repository so the demo works
  offline.
- Target current evergreen browsers. ES modules, `fetch`, CSS custom properties
  and `:has()` are all fair game.

## Repository layout

```
SalesPilot/
├── salespilot/              # Backend (READ-ONLY for frontend work)
│   └── static/              # Legacy console — FROZEN
├── frontend/
│   ├── customer/            # Customer chat app
│   └── admin/               # Trimmed staff console
├── docs/
│   ├── backend-contract.md  # API reference + changes required of the backend
│   └── frontend-changelog.md# Gated: update only when the user asks
├── data/knowledge_base.json
└── tests/                   # Backend tests
```

Shared frontend code (the gateway/adapter layer, the store, formatting helpers)
is duplicated deliberately rather than shared through a build step. Keep each app
self-contained; if a module must be shared, copy it and note the origin in a
comment.
