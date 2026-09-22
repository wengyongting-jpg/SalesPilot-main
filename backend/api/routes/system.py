# -*- coding: utf-8 -*-
"""Liveness and configuration visibility.

`/health` reports whether the backend is running **degraded**, meaning no model is
reachable and replies are being composed from templates. That belongs in a health
response rather than only in the logs: an operator about to demo should be able to see
it without reading a log file, and a template reply is otherwise indistinguishable from
a model one at a glance.
"""
from __future__ import annotations

from fastapi import APIRouter, Request

from ... import __version__, config
from ..deps import services_of

router = APIRouter(tags=["system"])


@router.get("/health")
def health(request: Request) -> dict:
    services = services_of(request)
    conversations = services.repo.list_opportunities()
    open_cases = sum(
        1 for case in services.repo.list_cases() if case.status.value == "Open"
    )
    no_model = services.conversation.runtime.model is None
    return {
        "status": "ok",
        "version": __version__,
        "conversations": len(conversations),
        "open_cases": open_cases,
        "provider": config.LLM_PROVIDER,
        "model": config.LLM_MODEL if not no_model else None,
        # True when replies are template-composed because no model is configured.
        "degraded": no_model,
        "degradation_reason": (
            "no model configured; replies are composed from templates"
            if no_model
            else None
        ),
    }
