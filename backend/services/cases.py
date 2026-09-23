# -*- coding: utf-8 -*-
"""Human cases and the other human review actions.

Three things a person does that the machine may not: own a case (open →
taken over → closed), disqualify a conversation, and release a held one. The
kernel decides *whether* a case is warranted (`kernel.hitl`); this module
carries the decision into storage and applies the lifecycle rules:

- one active case per opportunity — a new reason updates it (P0-3)
- closing a case hands the conversation back to the assistant
  (`interface-v1.md` §4.4): `human_takeover` and
  `human_intervention_required` are cleared
"""
from __future__ import annotations

from typing import Optional

from ..domain.case import HumanCase
from ..domain.enums import CaseStatus
from ..domain.opportunity import Opportunity
from ..kernel import hitl, qualification
from ..storage.base import Repository
from . import CaseNotFound, InvalidTransition, OpportunityNotFound


def open_or_update_case(
    repo: Repository, opp: Opportunity, *, reason: str, recommended_action: str
) -> tuple[HumanCase, bool]:
    """Return `(case, created)`. Never opens a second active case."""
    existing = repo.active_case_for(opp.id)
    if existing is not None:
        existing.reason = reason
        existing.recommended_action = recommended_action
        existing.state = opp.state
        existing.product = opp.product
        existing.summary = f"{existing.summary}\n[Update] {hitl.summarise(opp)} Reason: {reason}"
        repo.update_case(existing)
        return existing, False
    case = HumanCase(
        opportunity_id=opp.id,
        customer_name=opp.customer_name,
        state=opp.state,
        product=opp.product,
        reason=reason,
        summary=hitl.summarise(opp),
        recommended_action=recommended_action,
    )
    repo.add_case(case)
    return case, True


def parse_status(value: str) -> CaseStatus:
    """Accept enum names or serialised values; spaces/hyphens normalise (§4.4)."""
    raw = value.strip()
    try:
        return CaseStatus(raw)
    except ValueError:
        pass
    key = raw.upper().replace("-", "_").replace(" ", "_")
    try:
        return CaseStatus[key]
    except KeyError:
        raise InvalidTransition(f"unknown case status {value!r}") from None


def set_status(repo: Repository, case_id: str, status: CaseStatus) -> HumanCase:
    case = repo.get_case(case_id)
    if case is None:
        raise CaseNotFound(case_id)
    case.status = status
    repo.update_case(case)
    if status is CaseStatus.CLOSED:
        opp = repo.get_opportunity(case.opportunity_id)
        if opp is not None:
            opp.human_takeover = False
            opp.human_intervention_required = False
            repo.upsert_opportunity(opp)
    return case


def disqualify(repo: Repository, opportunity_id: str, *, reason: str) -> Opportunity:
    opp = _require(repo, opportunity_id)
    verdict = qualification.disqualify(opp, reason=reason)
    opp.qualification = verdict.level
    opp.qualification_reason = verdict.reason
    repo.upsert_opportunity(opp)
    return opp


def release(repo: Repository, opportunity_id: str, *, reason: Optional[str] = None) -> Opportunity:
    opp = _require(repo, opportunity_id)
    verdict = qualification.release(opp, reason=reason) if reason else qualification.release(opp)
    opp.qualification = verdict.level
    opp.qualification_reason = verdict.reason
    opp.solicitation_count = 0
    repo.upsert_opportunity(opp)
    return opp


def _require(repo: Repository, opportunity_id: str) -> Opportunity:
    opp = repo.get_opportunity(opportunity_id)
    if opp is None:
        raise OpportunityNotFound(opportunity_id)
    return opp
