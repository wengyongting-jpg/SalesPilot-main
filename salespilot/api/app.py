# -*- coding: utf-8 -*-
"""FastAPI application factory.

Exposes the SalesPilot agent workflow over HTTP so a WhatsApp-style frontend
or the future web Sales Dashboard can consume it. FastAPI is imported lazily
inside create_app() so importing the salespilot package never requires the
web dependencies.

Endpoints:
    GET  /health
    POST /api/messages              process one customer message
    GET  /api/opportunities         list opportunity profiles
    GET  /api/opportunities/{id}    one opportunity profile
    GET  /api/cases                 list HITL cases
    GET  /api/dashboard             text dashboard + queue summary
    GET  /api/analytics             FR-15 basic sales analytics
    POST /api/seed                  seed the scripted demo data (idempotent)
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from ..agent import SalesPilotAgent
from ..analytics import compute_analytics
from ..dashboard import render_dashboard
from ..seed import seed_demo_data
from ..storage import BaseRepository
from .schemas import (
    CaseStatusUpdate,
    IncomingMessage,
    serialize_agent_result,
    serialize_case,
    serialize_opportunity,
)

_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def create_app(
    repository: Optional[BaseRepository] = None,
    agent: Optional[SalesPilotAgent] = None,
):
    from fastapi import FastAPI, HTTPException
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import FileResponse

    sales_agent = agent or SalesPilotAgent(repository=repository)
    app = FastAPI(
        title="SalesPilot API",
        version="0.3.0",
        description="CareSure AI sales assistant - messaging, opportunity "
                    "tracking, scoring, HITL escalation, and web UI.",
    )

    # Serve frontend static assets
    if _STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(str(_STATIC_DIR / "index.html"))

    @app.get("/health")
    def health() -> dict:
        return {
            "status": "ok",
            "opportunities": len(sales_agent.repo.list_opportunities()),
            "open_cases": sum(
                1 for c in sales_agent.repo.list_cases()
                if c.status.value == "Open"
            ),
        }

    @app.post("/api/messages")
    def post_message(payload: IncomingMessage) -> dict:
        """Process one customer message through the full agent pipeline.

        P0-5 — idempotency. This endpoint mutates opportunity state: it appends
        the message, increments `turns`, and re-runs the state machine and
        scoring. Because the engagement dimension is derived from `turns`
        (`salespilot/engine/scoring.py`), a retry after a network timeout used to
        inflate the opportunity value score for an event that never happened.

        When the caller supplies `client_message_id`, the serialised response is
        stored as a receipt and a replay of the same key on the same conversation
        returns that stored response verbatim, without touching any state. This
        is replay semantics on purpose: the answer is "here is the response to
        that request", not "here is the current state". A client that needs fresh
        state re-reads GET /api/opportunities/{id}, which it already polls.

        Omitting `client_message_id` preserves the original behaviour exactly.
        """
        key = (payload.client_message_id or "").strip() or None

        # A blank customer_id means the agent will generate a fresh opportunity
        # id, so no earlier receipt can exist for it — skip the lookup rather
        # than guess a scope.
        scope = payload.customer_id.strip()
        if key and scope:
            cached = sales_agent.repo.get_message_receipt(scope, key)
            if cached is not None:
                return cached

        result = sales_agent.handle_message(
            customer_id=payload.customer_id,
            customer_name=payload.customer_name,
            text=payload.text,
            client_message_id=key,
        )
        response = serialize_agent_result(result)
        if key:
            # Keyed on the resolved opportunity id so a generated id is also
            # deduplicated on any subsequent replay.
            sales_agent.repo.save_message_receipt(
                result.opportunity.id, key, response
            )
        return response

    @app.get("/api/opportunities")
    def list_opportunities() -> dict:
        return {
            "count": len(sales_agent.repo.list_opportunities()),
            "items": [
                serialize_opportunity(opp)
                for opp in sales_agent.repo.list_opportunities()
            ],
        }

    @app.get("/api/opportunities/{opp_id}")
    def get_opportunity(opp_id: str) -> dict:
        opp = sales_agent.repo.get_opportunity(opp_id)
        if opp is None:
            raise HTTPException(status_code=404, detail="Opportunity not found")
        return serialize_opportunity(opp)

    @app.delete("/api/opportunities/{opp_id}")
    def delete_opportunity(opp_id: str) -> dict:
        """Reset a conversation by removing its opportunity (used by the UI
        'Reset' button). Idempotent: deleting a missing id is a no-op."""
        existed = sales_agent.repo.get_opportunity(opp_id) is not None
        sales_agent.repo.delete_opportunity(opp_id)
        return {"deleted": existed, "opportunity_id": opp_id}

    @app.get("/api/cases")
    def list_cases() -> dict:
        return {
            "count": len(sales_agent.repo.list_cases()),
            "items": [serialize_case(c) for c in sales_agent.repo.list_cases()],
        }

    @app.patch("/api/cases/{case_id}")
    def update_case_status(case_id: str, body: CaseStatusUpdate) -> dict:
        """Transition a case status: OPEN → TAKEN_OVER → CLOSED.

        A missing or malformed body is rejected by the request model with 422; an
        unknown status *value* still returns 400.
        """
        from ..models import CaseStatus
        case = next(
            (c for c in sales_agent.repo.list_cases() if c.id == case_id), None
        )
        if case is None:
            raise HTTPException(status_code=404, detail="Case not found")

        raw_status = body.status.upper().replace("-", "_").replace(" ", "_")
        try:
            new_status = CaseStatus[raw_status]
        except KeyError:
            try:
                new_status = CaseStatus(raw_status)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid status: {raw_status}")

        case.status = new_status
        # Closing a case resumes autonomous AI selling on the next customer
        # message. The admin console warns the representative about this, so the
        # behaviour must be preserved.
        if new_status == CaseStatus.CLOSED:
            opp = sales_agent.repo.get_opportunity(case.opportunity_id)
            if opp:
                opp.human_takeover = False
                opp.human_intervention_required = False
                sales_agent.repo.upsert_opportunity(opp)

        # `update_case` is declared on BaseRepository with a default
        # implementation, so every repository provides it. The previous
        # capability check plus `repo._cases` fallback was unreachable dead code
        # that reached into the in-memory repository's private state.
        sales_agent.repo.update_case(case)
        return serialize_case(case)

    @app.get("/api/dashboard")
    def dashboard() -> dict:
        opportunities = sales_agent.repo.list_opportunities()
        text = render_dashboard(sales_agent.repo)
        return {
            "text": text,
            "total": len(opportunities),
            "take_over": sum(1 for o in opportunities if o.human_takeover),
            "items": [serialize_opportunity(o) for o in opportunities],
        }

    @app.get("/api/analytics")
    def analytics() -> dict:
        return compute_analytics(sales_agent.repo)

    @app.post("/api/seed")
    def seed() -> dict:
        # Idempotent: demo conversation IDs are fixed, so skip once seeded
        if sales_agent.repo.list_opportunities():
            return {
                "seeded": False,
                "reason": "repository already contains opportunities",
            }
        summary = seed_demo_data(sales_agent)
        summary["seeded"] = True
        return summary

    return app
