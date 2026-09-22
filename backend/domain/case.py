# -*- coding: utf-8 -*-
"""A human escalation case: the handover record the sales representative works from.

One active case per opportunity. A new escalation reason while a case is already
open updates that case rather than creating a second one, so a queue never shows
the same customer twice.

The `reason` is load-bearing and must be accurate. A commercial negotiation
reported as a medical or underwriting matter sends the representative into the
conversation with the wrong preparation, which is why the previous build's
mislabelling was treated as a correctness bug rather than a wording problem.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from .enums import CaseStatus, OpportunityState, Product


def _now() -> datetime:
    return datetime.now()


def _new_id() -> str:
    return f"H-{uuid.uuid4().hex[:6].upper()}"


@dataclass
class HumanCase:
    opportunity_id: str
    customer_name: str
    state: OpportunityState
    product: Product
    reason: str
    summary: str
    recommended_action: str
    id: str = field(default_factory=_new_id)
    status: CaseStatus = CaseStatus.OPEN
    created_at: datetime = field(default_factory=_now)

    @property
    def is_active(self) -> bool:
        """Open or taken over — anything a representative still owns."""
        return self.status is not CaseStatus.CLOSED
