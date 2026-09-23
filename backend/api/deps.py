# -*- coding: utf-8 -*-
"""Request-scoped access to the objects `create_app` put on `app.state`."""
from __future__ import annotations

from fastapi import Request

from ..services.conversation import ConversationService
from ..storage.base import Repository


def get_repo(request: Request) -> Repository:
    return request.app.state.repo


def get_service(request: Request) -> ConversationService:
    return request.app.state.service
