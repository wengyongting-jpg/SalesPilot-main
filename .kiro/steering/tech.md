---
inclusion: always
---

# SalesPilot — technology and repository structure

## Runtime

- Backend: Python 3.10+, FastAPI/Uvicorn, SQLite or in-memory repository.
- Frontend: vanilla HTML, CSS and JavaScript ES modules; no build step, CDN or
  runtime dependency.
- Model access: only `backend/agent/` may invoke a model. Provider resolution is
  internal to the backend; browsers call only the REST API.

```powershell
py -3 -m pip install -r requirements.txt
py -3 -m backend --serve --seed
py -3 -m backend --demo
py -3 -m unittest discover -s backend/tests
node --test "frontend/tests/**/*.test.js"
```

The customer and admin apps are served statically from `frontend/`, normally on
port 8123, and call the backend on port 8000. The customer tier receives only the
safe transcript projection; the admin tier receives sales intelligence.

## Repository layout

```text
backend/                 API, services, kernel, agent, storage and observability
backend/tests/           Backend suite
frontend/customer/       Customer chat
frontend/admin/          Staff console
frontend/tests/          Dependency-free Node tests
data/                    Approved knowledge and local runtime data
evals/                   Multi-turn evaluation fixtures and runner
docs/api/interface-v1.md Shared HTTP contract
```

Shared frontend code is duplicated deliberately so each static app is
self-contained. All network access stays in gateway modules; views only render
state, and stores hold presentation state rather than business rules.
