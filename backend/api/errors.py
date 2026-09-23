# -*- coding: utf-8 -*-
"""Service errors → HTTP status codes, in FastAPI's default `{"detail": …}` shape.

`interface-v1.md` §4.5: there is no application-specific error envelope.
Anything not mapped here is a program error and surfaces as FastAPI's own
500 — `docs/backend-plan.md` §7's first failure class, never disguised.
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ..services import (
    CaseNotFound,
    InvalidCursor,
    InvalidTransition,
    NotUnderTakeover,
    OpportunityNotFound,
)

_STATUS = {
    OpportunityNotFound: (404, "Opportunity not found"),
    CaseNotFound: (404, "Case not found"),
    NotUnderTakeover: (409, "Conversation is not under human takeover"),
    InvalidTransition: (400, "Invalid status"),
    InvalidCursor: (400, "Invalid since cursor"),
}


def install(app: FastAPI) -> None:
    for exc_type, (status, message) in _STATUS.items():
        app.add_exception_handler(exc_type, _handler(status, message))


def _handler(status: int, message: str):
    async def handle(_request: Request, exc: Exception) -> JSONResponse:
        detail = f"{message}: {exc}" if str(exc) else message
        return JSONResponse(status_code=status, content={"detail": detail})

    return handle
