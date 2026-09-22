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

from ...services.cases import UnknownCase, parse_status
from ...services.rep_reply import NotUnderTakeover, UnknownOpportunity
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

router = APIRouter(prefix="/api/admin", tags=["admin"])


# ---- Opportunities --------------------------------------------------------


@router.get("/opportunities")
def list_opportunities(request: Request, history_limit: Optional[int] = None) -> dict:
    repo = services_of(request).repo
    opportunities = [
        opportunity_to_dict(opp)
        for opp in repo.list_opportunities()
    ]
    if history_limit is not None:
        for payload in opportunities:
            payload["score_history"] = payload["score_history"][-history_limit:]
            payload["state_history"] = payload["state_history"][-history_limit:]
    return {"count": len(opportunities), "items": opportunities}


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
        raise errors.not_found("Opportunity not found")

    payload = opportunity_to_dict(opportunity)
    if since is not None:
        try:
            newer = repo.messages_since(opportunity_id, cursor=since)
        except MalformedCursor as error:
            raise errors.bad_request(str(error))
        payload["messages"] = [message_to_dict(message) for message in newer]
    return payload


@router.get("/opportunities/{opportunity_id}/cost")
def conversation_cost(opportunity_id: str, request: Request) -> dict:
    """Token and money totals across every run of one conversation.

    `interface-v1.md` §5.3 item 6. Reported next to the conversation that incurred it
    rather than only in aggregate, so a demo operator can point at one exchange.
    """
    return services_of(request).repo.conversation_totals(opportunity_id)


@router.post("/opportunities/{opportunity_id}/rep-reply")
def rep_reply(opportunity_id: str, body: RepReplyRequest, request: Request) -> dict:
    """A human representative replying inside the console. §5.4.

    Refused with 409 when nobody has taken the conversation over, so this cannot become
    a way to inject text while the assistant is still selling autonomously.
    """
    try:
        message = services_of(request).rep_reply.reply(
            opportunity_id,
            text=body.text,
            rep_name=body.rep_name,
            client_message_id=body.client_message_id,
        )
    except UnknownOpportunity as error:
        raise errors.not_found(str(error))
    except NotUnderTakeover as error:
        raise errors.conflict(str(error))
    return {"opportunity_id": opportunity_id, "message": message_to_dict(message)}


# ---- Cases ----------------------------------------------------------------


@router.get("/cases")
def list_cases(request: Request) -> dict:
    cases = [case_to_dict(case) for case in services_of(request).cases.list_cases()]
    return {"count": len(cases), "items": cases}


@router.patch("/cases/{case_id}")
def update_case(case_id: str, body: CaseStatusUpdate, request: Request) -> dict:
    """Transition a case: Open -> Taken Over -> Closed.

    Closing clears `human_takeover`, which resumes autonomous selling on the customer's
    next message. Any UI offering "resolve" has to say so.
    """
    try:
        status = parse_status(body.status)
    except ValueError as error:
        raise errors.bad_request(str(error))
    try:
        case = services_of(request).cases.transition(case_id, status)
    except UnknownCase as error:
        raise errors.not_found(str(error))
    return case_to_dict(case)


# ---- Agent runs -----------------------------------------------------------


@router.get("/agent-runs")
def list_agent_runs(
    request: Request,
    opportunity_id: str,
    client_message_id: Optional[str] = None,
    limit: Optional[int] = None,
) -> dict:
    """Runs for one conversation, newest first.

    `client_message_id` is the correlation key from `interface-v1.md` §3: the embedded
    customer app reports the key it sent, and the console joins on it to fetch the
    telemetry the customer app is never given.
    """
    runs = services_of(request).repo.list_agent_runs(
        opportunity_id, client_message_id=client_message_id, limit=limit
    )
    return {"count": len(runs), "items": runs}


@router.get("/agent-runs/{run_id}")
def get_agent_run(run_id: str, request: Request) -> dict:
    run = services_of(request).repo.get_agent_run(run_id)
    if run is None:
        raise errors.not_found("Agent run not found")
    return run


# ---- Aggregates -----------------------------------------------------------


@router.get("/analytics")
def analytics(request: Request) -> dict:
    return services_of(request).analytics.compute()


@router.get("/dashboard")
def dashboard(request: Request) -> dict:
    """The queue, as data.

    No pre-rendered text: the frozen build returned a CLI-formatted block that a web
    console had to ignore, which meant one of the two renderings was always stale.
    """
    services = services_of(request)
    opportunities = services.repo.list_opportunities()
    sellable = [opp for opp in opportunities if opp.is_sellable]
    # The queue needs the latest message for its preview, not an ever-growing
    # transcript or score/state histories. Full detail stays on the opportunity
    # endpoint and is loaded only when an operator opens a row.
    items = []
    for opportunity in sellable:
        item = opportunity_to_dict(opportunity)
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


@router.post("/seed")
def seed_demo_data(request: Request) -> dict:
    """Seed the scripted demo conversations. Idempotent."""
    return seed(services_of(request).conversation)
