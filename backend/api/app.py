# -*- coding: utf-8 -*-
"""Application factory: middleware, error handlers, and the two tiers' routers.

No static UI is served here (`docs/backend-plan.md` §4 rule 7): the two
frontends under `frontend/` are served from their own origin, which is why
CORS is on. No authentication anywhere — an accepted, documented demo
limitation that is not disguised with a fake login.
"""
from __future__ import annotations

from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import backend

from .. import config
from ..services.conversation import ConversationService, build_service
from ..storage import MemoryRepository
from ..storage.base import Repository
from . import errors
from .routes import admin, customer, system


def create_app(
    repo: Optional[Repository] = None,
    service: Optional[ConversationService] = None,
) -> FastAPI:
    repo = repo or MemoryRepository()
    service = service or build_service(repo)

    app = FastAPI(
        title="SalesPilot backend",
        version=backend.__version__,
        description=(
            "CareSure AI sales assistant. Customer tier under /api/messages and "
            "/api/conversations; staff tier under /api/admin. See docs/api/interface-v1.md."
        ),
    )
    app.state.repo = repo
    app.state.service = service

    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.CORS_ORIGINS,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    errors.install(app)

    app.include_router(system.router, tags=["system"])
    app.include_router(customer.router, prefix="/api", tags=["customer"])
    app.include_router(admin.router, prefix="/api/admin", tags=["admin"])
    app.include_router(admin.admin_only, prefix="/api/admin", tags=["admin"])
    # Migration aliases at the frozen build's paths (interface-v1 §5.1).
    app.include_router(admin.router, prefix="/api", include_in_schema=False)
    return app
