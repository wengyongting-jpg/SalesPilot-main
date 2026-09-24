# -*- coding: utf-8 -*-
"""The service bundle the route modules share.

Built once by `create_app` and attached to the application, so a route reads it rather
than constructing anything. That keeps the repository a single instance — with SQLite,
two connections opened per request would be both slower and a lock waiting to happen.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import Request

from ..services.analytics import AnalyticsService
from ..services.cases import CaseService
from ..services.conversation import ConversationService
from ..services.rep_reply import RepReplyService
from ..storage.base import Repository


@dataclass
class Services:
    repo: object
    conversation: ConversationService
    cases: CaseService
    rep_reply: RepReplyService
    analytics: AnalyticsService

    @classmethod
    def build(
        cls,
        repository,
        *,
        conversation: Optional[ConversationService] = None,
    ) -> "Services":
        from ..agent.extraction.rules import RuleExtractor
        from ..agent.reply.template import TemplateComposer

        conversation = conversation or ConversationService(
            repository,
            extractor=RuleExtractor(),
            composer=TemplateComposer(),
        )
        return cls(
            repo=repository,
            conversation=conversation,
            cases=CaseService(repository),
            rep_reply=RepReplyService(repository),
            analytics=AnalyticsService(repository),
        )


def services_of(request: Request) -> Services:
    return request.app.state.services


# Backward compatibility aliases for Main's route files
def get_repo(request: Request) -> Repository:
    return services_of(request).repo


def get_service(request: Request) -> ConversationService:
    return services_of(request).conversation


# Alias for Kevin-work's app.py
services = services_of
