# -*- coding: utf-8 -*-
"""The FastAPI application factory.

Two route groups, split by visibility tier, plus liveness. No static files and no
legacy console: the two applications under `frontend/` replace it, and `/` returning
404 is the honest answer rather than serving a third UI nobody maintains.

FastAPI is imported inside `create_app` so importing `backend` never requires the web
dependencies — `domain` and `kernel` in particular stay usable with nothing installed.
"""
from __future__ import annotations

from typing import Optional

from .. import __version__, config
from ..observability.logging import get_logger
from .deps import Services, services


def create_app(
    repository=None,
    *,
    model=None,
    conversation=None,
    title: str = "SalesPilot backend",
):
    from fastapi import FastAPI

    from .routes import admin, customer, system

    if repository is None:
        from ..storage.sqlite import SqliteRepository

        repository = SqliteRepository()

    app = FastAPI(
        title=title,
        version=__version__,
        description=(
            "CareSure AI sales assistant. Two surfaces, split by visibility tier: "
            "the customer response has no shape for sales intelligence, and the admin "
            "surface carries it in full including model telemetry. No authentication "
            "exists anywhere; that is a recorded demo limitation."
        ),
    )
    app.state.services = Services.build(
        repository, conversation=conversation
    )

    # Install exception handlers
    from . import errors
    errors.install(app)

    _allow_development_origins(app)

    app.include_router(system.router)
    app.include_router(customer.router)
    app.include_router(admin.router)

    logger = get_logger()
    logger.info(
        "api ready | provider=%s | model=%s | telemetry_content=%s | cors=%s",
        config.LLM_PROVIDER,
        config.LLM_MODEL if model is not None else "(none)",
        "on" if config.TELEMETRY_CONTENT else "off",
        ",".join(config.CORS_ORIGINS) or "none",
    )
    return app


def _allow_development_origins(app) -> None:
    """Let the two frontends reach the API from a browser.

    They are served as static files on another port, so they are permanently
    cross-origin, and the browser rejects every `fetch` before it reaches the backend.
    Nothing on the frontend side can fix that: a static file server cannot add a header
    to somebody else's response, and proxying would mean a dev-server dependency that
    the frontend's no-dependency rule forbids.

    **Security note, since this opens cross-origin access.** The allowed list comes
    from configuration and defaults to loopback development origins only. A wildcard is
    avoided even though nothing here is protected, because it would set a habit that
    becomes a real hole the moment authentication exists. `allow_credentials` stays off:
    there is no session or cookie to carry, so enabling it would widen the surface for
    no benefit. Contract and acceptance criteria: `docs/v0.0/backend/backend-contract.md` item 15.
    """
    if not config.CORS_ORIGINS:
        return

    from fastapi.middleware.cors import CORSMiddleware

    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.CORS_ORIGINS,
        # PATCH transitions a case, DELETE resets a conversation. Both are used by the
        # shipped frontends, so omitting them would leave the console half working.
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type"],
        allow_credentials=False,
    )
