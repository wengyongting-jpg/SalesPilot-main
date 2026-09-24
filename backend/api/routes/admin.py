# -*- coding: utf-8 -*-
"""The admin surface. `docs/api/interface-v1.md` §5.1, §5.3, §5.4.

The inverse of the customer tier: full sales intelligence, including model telemetry.
Responses are the service layer's canonical dictionaries, so the console reads exactly
what the pipeline produced rather than a re-declared copy of it.

There is no authentication here, or anywhere. That is a recorded and accepted demo
limitation, not an oversight: anyone who can reach this surface can read every
transcript and take over any case. It is documented in `interface-v1.md` §2 and
`.kiro/steering/product.md`, deliberately rather than papered over with a fake login.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Request

from ...services import CaseNotFound, OpportunityNotFound
from ...services.cases import parse_status
from ...services.seeding import seed
from ...services.serialisation import (
    case_to_dict,
    message_to_dict,
    opportunity_to_dict,
)
from ...storage.base import MalformedCursor
from .. import errors
from ..deps import services_of
from ..schemas.admin import CaseStatusUpdate, RepReplyRequest

router = APIRouter(tags=["admin"], prefix="/api/admin")


@router.get("/opportunities")
def list_opportunities(request: Request, history_limit: Optional[int] = None) -> dict:
    """All opportunities with optional history trimming."""
    repo = services_of(request).repo
    opportunities = [
        opportunity_to_dict(repo.get_opportunity(opp.id, history_limit=history_limit))
        for opp in repo.list_opportunities()
    ]
    return {"count": len(opportunities), "items": opportunities}


@router.get("/dashboard")
def dashboard(request: Request) -> dict:
    """The queue. `docs/api/interface-v1.md` §5.2.

    Does not return the full detail per item — it trims messages, score history and
    state history so a 100-item list does not carry 100 full transcripts. The admin
    console's grid is shallow by design; full detail lives on the opportunity endpoint
    and is loaded only when the operator opens a row.
    """
    services = services_of(request)
    opportunities = services.repo.list_opportunities()

    # Exclude held, which are not autonomous sales yet and the gap task says are not
    # for the queue.
    from ...domain.enums import Qualification
    sellable = [o for o in opportunities if o.qualification is not Qualification.HELD]

    # Trim to the shapes the console grid actually uses. One message, zero histories:
    # faster than loading every field on 100 profiles, and avoids an ever-growing
    # transcript or score/state histories. Full detail stays on the opportunity
    # endpoint and is loaded only when an operator opens a row.
    items = []
    for opportunity in sellable:
        item = opportunity_to_dict(opportunity)
        active_case = services.repo.active_case_for(opportunity.id)
        item["attention_reason"] = (
            active_case.reason if active_case else
            opportunity.pending_handoff_reason or opportunity.main_concern
        )
        item["messages"] = item["messages"][-1:]
        item["score_history"] = []
        item["state_history"] = []
        items.append(item)

    return {
        "total": len(sellable),
        "held": len(opportunities) - len(sellable),
        "take_over": sum(1 for opp in sellable if opp.human_takeover),
        "items": items,
    }


@router.get("/opportunities/{opportunity_id}")
def get_opportunity(
    opportunity_id: str,
    request: Request,
    since: Optional[str] = None,
    history_limit: Optional[int] = None,
) -> dict:
    """One profile in full.

    `since` and `history_limit` exist because this is the endpoint the console polls,
    and it carries the most fields — gap register item 12. Without them a poll grows
    with the conversation, which compounds to quadratic traffic over a session.
    """
    repo = services_of(request).repo
    opportunity = repo.get_opportunity(opportunity_id, history_limit=history_limit)
    if opportunity is None:
        raise OpportunityNotFound(opportunity_id)

    payload = opportunity_to_dict(opportunity)
    if since is not None:
        try:
            from ...services import opportunities as opp_service
            newer = opp_service.messages_since(opportunity, cursor=since)
        except MalformedCursor as error:
            raise errors.bad_request(str(error))
        payload["messages"] = [message_to_dict(message) for message in newer]
    return payload


@router.get("/opportunities/{opportunity_id}/cost")
def get_opportunity_cost(opportunity_id: str, request: Request) -> dict:
    """Token totals for one opportunity. `docs/api/interface-v1.md` §5.5."""
    repo = services_of(request).repo
    runs = repo.list_runs(opportunity_id=opportunity_id)

    # Calculate total cost
    total_cost = 0.0
    pricing_known = True  # Assume known until we find a run without cost
    for run in runs:
        if run.get("total_cost"):
            total_cost += run["total_cost"]["amount"]
        else:
            pricing_known = False

    return {
        "run_count": len(runs),
        "total_tokens": sum(run.get("totals", {}).get("total_tokens", 0) for run in runs),
        "input_tokens": sum(run.get("totals", {}).get("input_tokens", 0) for run in runs),
        "output_tokens": sum(run.get("totals", {}).get("output_tokens", 0) for run in runs),
        "cost": {
            "amount": round(total_cost, 5),
            "pricing_known": pricing_known,
        },
    }


@router.post("/opportunities/{opportunity_id}/rep-reply")
def post_rep_reply(
    opportunity_id: str, payload: RepReplyRequest, request: Request
) -> dict:
    """Append a representative's own message. `docs/api/interface-v1.md` §5.4."""
    message = services_of(request).rep_reply.reply(
        opportunity_id,
        text=payload.text,
        rep_name=payload.rep_name,
        client_message_id=payload.client_message_id,
    )
    return message_to_dict(message)


@router.get("/cases")
def list_cases(request: Request) -> dict:
    """All cases, open and closed."""
    cases = services_of(request).repo.list_cases()
    items = [case_to_dict(case) for case in cases]
    return {"count": len(items), "items": items}


@router.get("/cases/{case_id}")
def get_case(case_id: str, request: Request) -> dict:
    """One case in full."""
    case = services_of(request).repo.get_case(case_id)
    if case is None:
        raise CaseNotFound(case_id)
    return case_to_dict(case)


@router.patch("/cases/{case_id}")
def update_case_status(
    case_id: str, payload: CaseStatusUpdate, request: Request
) -> dict:
    """Transition a case. `docs/api/interface-v1.md` §4.4."""
    status = parse_status(payload.status)
    case = services_of(request).cases.set_status(case_id, status)
    return case_to_dict(case)


@router.get("/analytics")
def get_analytics(request: Request) -> dict:
    """Counts and breakdowns. `docs/api/interface-v1.md` §4.2."""
    return services_of(request).analytics.compute_analytics()


@router.get("/agent-runs")
def list_runs(
    request: Request,
    opportunity_id: Optional[str] = None,
    client_message_id: Optional[str] = None,
    limit: int = 50,
) -> dict:
    """List agent runs with optional filters. `docs/api/interface-v1.md` §4.3."""
    repo = services_of(request).repo
    runs = repo.list_runs(
        opportunity_id=opportunity_id,
        client_message_id=client_message_id,
        limit=limit,
    )
    return {"items": runs, "count": len(runs)}


@router.get("/agent-runs/{run_id}")
def get_run(run_id: str, request: Request) -> dict:
    """One agent run in full. `docs/api/interface-v1.md` §4.3."""
    run = services_of(request).repo.get_run(run_id)
    if run is None:
        raise errors.not_found(f"Run {run_id} not found")
    return run


@router.post("/seed")
def seed_demo_data(request: Request) -> dict:
    """Seed the scripted demo conversations. Idempotent."""
    return seed(services_of(request).conversation)
