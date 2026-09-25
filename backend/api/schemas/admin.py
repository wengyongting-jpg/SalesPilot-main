# -*- coding: utf-8 -*-
"""Admin-tier request models, and the shapes the staff console reads.

The inverse of the customer tier: this side keeps the full sales intelligence,
including model telemetry. Responses are passed through as the service's canonical
dictionaries rather than re-declared as models — the admin console is the one consumer
and it reads fields directly, so a second hand-maintained copy of the shape would be a
drift risk with no benefit.

Requests *are* modelled, because they are input and must be validated.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

_STRICT = ConfigDict(extra="forbid")


class CaseStatusUpdate(BaseModel):
    """Body of `PATCH /api/admin/cases/{id}`.

    Accepts an enum name (`TAKEN_OVER`) or a serialised value (`"Taken Over"`);
    spaces and hyphens normalise to underscores. A missing or malformed body is a 422
    from this model; an unrecognised *value* is a 400 from the handler, because the two
    are different mistakes and a client should be able to tell them apart.
    """

    model_config = _STRICT

    status: str = Field(..., min_length=1)


class RepReplyRequest(BaseModel):
    """Body of `POST /api/admin/opportunities/{id}/rep-reply`."""

    model_config = _STRICT

    text: str = Field(..., min_length=1)
    rep_name: Optional[str] = None
    client_message_id: Optional[str] = None
