# -*- coding: utf-8 -*-
"""Use-cases. The application layer.

Owns what a single request means end to end: idempotency, the order of
operations, persistence, and recording the agent run. Composes `agent` (which
understands and words) with `kernel` (which decides) -- neither of which knows
about the other.

The only package that writes storage.
"""
from __future__ import annotations


class ServiceError(Exception):
    """Base for errors the HTTP layer maps to a status code."""


class OpportunityNotFound(ServiceError):
    pass


class CaseNotFound(ServiceError):
    pass


class NotUnderTakeover(ServiceError):
    """A representative action on a conversation no representative owns (→ 409)."""


class InvalidTransition(ServiceError):
    """A status value the case lifecycle does not accept (→ 400)."""


class InvalidCursor(ServiceError):
    """A `since` value that is neither an ISO-8601 timestamp nor a message id (→ 400)."""
