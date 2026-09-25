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

from typing import Optional, Union

from ..domain.case import HumanCase
from ..domain.enums import CaseStatus
from ..domain.opportunity import Opportunity
from ..kernel import hitl, qualification
from ..observability.logging import get_logger
from ..storage.base import Repository
from . import CaseNotFound, InvalidTransition, OpportunityNotFound


class CaseService:
    """Service wrapper for case management functions."""

    def __init__(self, repo: Repository) -> None:
        self.repo = repo
        self.logger = get_logger()

    def list_cases(self) -> list[HumanCase]:
        return self.repo.list_cases()

    def get(self, case_id: str) -> HumanCase:
        case = self.repo.get_case(case_id)
        if case is None:
            raise CaseNotFound(f"no case with id {case_id!r}")
        return case

    def transition(
        self, case_id: str, status: Union[CaseStatus, str]
    ) -> HumanCase:
        """Transition a case through its lifecycle."""
        case = self.get(case_id)
        new_status = parse_status(status)
        case.status = new_status
        self.repo.update_case(case)

        if new_status is CaseStatus.TAKEN_OVER:
            self._claim(case.opportunity_id)
        elif new_status is CaseStatus.CLOSED:
            self._resume_autonomy(case.opportunity_id)

        self.logger.info(
            "case %s | %s -> %s", case.id, case.opportunity_id, case.status.value
        )
        return case

    def set_status(self, case_id: str, status: Union[CaseStatus, str]) -> HumanCase:
        """Alias for transition() to match API route expectations."""
        return self.transition(case_id, status)

    def _claim(self, opportunity_id: str) -> None:
        """A representative now owns the conversation."""
        opp = self.repo.get_opportunity(opportunity_id)
        if opp is None:
            return
        opp.human_takeover = True
        self.repo.upsert_opportunity(opp)

    def _resume_autonomy(self, opportunity_id: str) -> None:
        """Close the case and resume autonomous selling."""
        opp = self.repo.get_opportunity(opportunity_id)
        if opp is None:
            return
        opp.human_takeover = False
        opp.human_intervention_required = False
        self.repo.upsert_opportunity(opp)


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


def parse_status(value: Union[CaseStatus, str]) -> CaseStatus:
    """Accept enum, name, or serialised value."""
    if isinstance(value, CaseStatus):
        return value
    raw = str(value).strip()
    try:
        return CaseStatus[raw.upper().replace("-", "_").replace(" ", "_")]
    except KeyError:
        pass
    try:
        return CaseStatus(raw)
    except ValueError:
        pass
    normalized = raw.replace("-", "_").replace(" ", "_").upper()
    try:
        return CaseStatus[normalized]
    except KeyError as error:
        raise InvalidTransition(f"invalid case status: {raw!r}") from error


def set_status(repo: Repository, case_id: str, status: CaseStatus) -> HumanCase:
    case = repo.get_case(case_id)
    if case is None:
        raise CaseNotFound(f"no case with id {case_id!r}")
    case.status = status
    repo.update_case(case)
    return case


def disqualify(repo: Repository, opportunity_id: str, *, reason: str) -> Opportunity:
    opp = _require(repo, opportunity_id)
    opp.qualification = qualification.disqualify(opp, reason=reason)
    repo.upsert_opportunity(opp)
    return opp


def release(repo: Repository, opportunity_id: str, *, reason: Optional[str] = None) -> Opportunity:
    opp = _require(repo, opportunity_id)
    opp.human_intervention_required = False
    if reason:
        opp.main_concern = reason
    repo.upsert_opportunity(opp)
    return opp


def _require(repo: Repository, opportunity_id: str) -> Opportunity:
    opp = repo.get_opportunity(opportunity_id)
    if opp is None:
        raise OpportunityNotFound(f"no opportunity with id {opportunity_id!r}")
    return opp
