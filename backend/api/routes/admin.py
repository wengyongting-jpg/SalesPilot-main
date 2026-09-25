# -*- coding: utf-8 -*-
"""The staff console's surface — `/api/admin/*`.

Two routers. `router` carries the endpoints the frozen build already had and
is mounted twice — under `/api/admin` and, as `interface-v1.md` §5.1 allows
during migration, at the old `/api` paths. `admin_only` carries what only
the rebuild offers (agent runs, rep reply, the qualification actions) and is
mounted once. Full intelligence everywhere; this is the tier that may see it.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from ... import config
from ...services import analytics, cases, opportunities, seeding
from ...services.conversation import ConversationService
from ...services.rep_reply import append_rep_reply
from ...storage.base import Repository
from ..deps import get_repo, get_service
from ..schemas.admin import DEFAULT_HISTORY_LIMIT, opportunity_to_wire, summary_to_wire
from ..schemas.shared import (
    CaseStatusUpdate,
    DisqualifyIn,
    ReleaseIn,
    RepReplyIn,
    case_to_wire,
    message_to_wire,
)

router = APIRouter()
admin_only = APIRouter()


# ---- Opportunities -------------------------------------------------------------


@router.get("/opportunities")
def list_opportunities(repo: Repository = Depends(get_repo)) -> dict:
    items = [summary_to_wire(o) for o in repo.list_opportunities()]
    return {"count": len(items), "items": items}


@router.get("/opportunities/{opportunity_id}")
def get_opportunity(
    opportunity_id: str,
    since: Optional[str] = Query(default=None),
    history_limit: int = Query(default=DEFAULT_HISTORY_LIMIT, ge=1, le=1000),
    repo: Repository = Depends(get_repo),
) -> dict:
    opp = opportunities.require(repo, opportunity_id)
    return opportunity_to_wire(
        opp,
        messages=opportunities.messages_since(opp, since),
        case=repo.active_case_for(opp.id),
        next_best_action=opportunities.current_next_best_action(opp),
        history_limit=history_limit,
    )


@router.delete("/opportunities/{opportunity_id}")
def delete_opportunity(opportunity_id: str, repo: Repository = Depends(get_repo)) -> dict:
    return {"deleted": opportunities.reset(repo, opportunity_id), "opportunity_id": opportunity_id}


# ---- Cases ---------------------------------------------------------------------


@router.get("/cases")
def list_cases(repo: Repository = Depends(get_repo)) -> dict:
    items = [case_to_wire(c) for c in repo.list_cases()]
    return {"count": len(items), "items": items}


@router.patch("/cases/{case_id}")
def update_case(case_id: str, body: CaseStatusUpdate, repo: Repository = Depends(get_repo)) -> dict:
    status = cases.parse_status(body.status)
    return case_to_wire(cases.set_status(repo, case_id, status))


# ---- Dashboard, analytics, seed ----------------------------------------------


@router.get("/dashboard")
def dashboard(repo: Repository = Depends(get_repo)) -> dict:
    opps = repo.list_opportunities()
    return {
        "text": seeding.render_summary(repo),
        "total": len(opps),
        "take_over": sum(1 for o in opps if o.human_takeover),
        "items": [summary_to_wire(o) for o in opps],
    }


@router.get("/analytics")
def get_analytics(repo: Repository = Depends(get_repo)) -> dict:
    return analytics.compute_analytics(repo)


@router.post("/seed")
def seed(service: ConversationService = Depends(get_service)) -> dict:
    return seeding.seed(service)


# ---- Rebuild-only ------------------------------------------------------------------


@admin_only.get("/agent-runs")
def list_agent_runs(
    opportunity_id: Optional[str] = Query(default=None),
    client_message_id: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    repo: Repository = Depends(get_repo),
) -> dict:
    items = repo.list_runs(opportunity_id=opportunity_id, client_message_id=client_message_id, limit=limit)
    return {"count": len(items), "items": items, "content_enabled": config.TELEMETRY_CONTENT}


@admin_only.get("/agent-runs/{run_id}")
def get_agent_run(run_id: str, repo: Repository = Depends(get_repo)) -> dict:
    run = repo.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Agent run not found")
    return run


@admin_only.post("/opportunities/{opportunity_id}/rep-reply")
def rep_reply(opportunity_id: str, body: RepReplyIn, repo: Repository = Depends(get_repo)) -> dict:
    message = append_rep_reply(
        repo,
        opportunity_id,
        text=body.text,
        rep_name=body.rep_name,
        client_message_id=body.client_message_id,
    )
    return {"message": message_to_wire(message)}


@admin_only.post("/opportunities/{opportunity_id}/disqualify")
def disqualify(opportunity_id: str, body: DisqualifyIn, repo: Repository = Depends(get_repo)) -> dict:
    return summary_to_wire(cases.disqualify(repo, opportunity_id, reason=body.reason))


@admin_only.post("/opportunities/{opportunity_id}/release")
def release(
    opportunity_id: str, body: Optional[ReleaseIn] = None, repo: Repository = Depends(get_repo)
) -> dict:
    return summary_to_wire(cases.release(repo, opportunity_id, reason=body.reason if body else None))


@admin_only.get("/held")
def held(repo: Repository = Depends(get_repo)) -> dict:
    items = [summary_to_wire(o) for o in opportunities.held(repo)]
    return {"count": len(items), "items": items}


@admin_only.get("/opportunities/{opportunity_id}/score-explain")
def score_explain(opportunity_id: str, repo: Repository = Depends(get_repo)) -> dict:
    opp = opportunities.require(repo, opportunity_id)
    return opportunities.score_explanation(opp)
