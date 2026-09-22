# -*- coding: utf-8 -*-
"""Human case transitions: Open -> Taken Over -> Closed.

The behaviour worth naming is what **closing** does: it clears `human_takeover`, which
resumes autonomous selling on the customer's next message. The admin console tells the
representative that will happen, so if this stopped doing it the console's warning
would become a lie. It is asserted rather than assumed.

Taking a case over does *not* clear the flag — it **sets** it, which is the point of
taking it over. The two directions have to be symmetric, because the console's whole
workflow is the round trip:

    -> TAKEN_OVER   human_takeover = True,  intervention flag left as-is
    -> CLOSED       human_takeover = False, intervention flag cleared
    -> OPEN         both unchanged

Reopening deliberately does nothing: an open case means the assistant is still handling
the conversation and nobody has claimed it.

Only the escalation path used to set the flag, so taking a case over through the API
left it false and the following rep reply was refused with "take over first" — said to
an operator who had just done exactly that. Specification and acceptance criteria:
`docs/backend-contract.md` item 14.
"""
from __future__ import annotations

from typing import Optional, Union

from ..domain.case import HumanCase
from ..domain.enums import CaseStatus
from ..observability.logging import get_logger


class UnknownCase(Exception):
    """No case with that id."""


class CaseService:
    def __init__(self, repo) -> None:
        self.repo = repo
        self.logger = get_logger()

    def list_cases(self) -> list[HumanCase]:
        return self.repo.list_cases()

    def get(self, case_id: str) -> HumanCase:
        case = self.repo.get_case(case_id)
        if case is None:
            raise UnknownCase(f"no case with id {case_id!r}")
        return case

    def transition(
        self, case_id: str, status: Union[CaseStatus, str]
    ) -> HumanCase:
        case = self.get(case_id)
        case.status = parse_status(status)
        self.repo.update_case(case)

        if case.status is CaseStatus.TAKEN_OVER:
            self._claim(case.opportunity_id)
        elif case.status is CaseStatus.CLOSED:
            self._resume_autonomy(case.opportunity_id)

        self.logger.info(
            "case %s | %s -> %s", case.id, case.opportunity_id, case.status.value
        )
        return case

    def _claim(self, opportunity_id: str) -> None:
        """A representative now owns the conversation, so the assistant stops selling.

        `human_intervention_required` is left alone on purpose: it records that a person
        was *needed*, which taking the case over does not change. Clearing it here would
        lose the reason the case was opened.
        """
        opp = self.repo.get_opportunity(opportunity_id)
        if opp is None:
            return
        opp.human_takeover = True
        self.repo.upsert_opportunity(opp)

    def _resume_autonomy(self, opportunity_id: str) -> None:
        opp = self.repo.get_opportunity(opportunity_id)
        if opp is None:
            return
        opp.human_takeover = False
        opp.human_intervention_required = False
        self.repo.upsert_opportunity(opp)


def parse_status(status: Union[CaseStatus, str]) -> CaseStatus:
    """Accept an enum, an enum name, or a serialised value.

    Clients send `TAKEN_OVER` and `"Taken Over"` interchangeably, and normalising here
    keeps that leniency in one place instead of spread across the route handlers.
    """
    if isinstance(status, CaseStatus):
        return status
    raw = str(status).strip()
    try:
        return CaseStatus[raw.upper().replace("-", "_").replace(" ", "_")]
    except KeyError:
        pass
    try:
        return CaseStatus(raw)
    except ValueError as error:
        raise ValueError(f"invalid case status: {raw!r}") from error
