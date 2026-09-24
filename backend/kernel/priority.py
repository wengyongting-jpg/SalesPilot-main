# -*- coding: utf-8 -*-
"""Priority: derived from both axes as a matrix, never by thresholding one number.

Specification: `docs/backend-contract.md` gap register item 13.

The wire values are unchanged — `HIGH`, `MEDIUM`, `LOW` — so badge and count logic
in the admin console is unaffected. Only the derivation changes.

Why a matrix rather than a threshold on a combined total: averaging the two axes
first destroys the distinction that made separating them worthwhile. A conversation
with no fit and frantic activity averages to the same number as a good fit with
moderate activity, and those two need opposite treatment. The matrix keeps them
apart:

                            behaviour
    fit          hot (>=70)   warm (>=40)   cold (<40)
    A (>=70)     HIGH         HIGH          MEDIUM
    B (>=40)     HIGH         MEDIUM        LOW
    C (<40)      MEDIUM       LOW           LOW

Reading the bottom-left cell is the point: strong behaviour with no fit reaches
MEDIUM at most. That is the spam case, and on the frozen build it reached HIGH.
"""
from __future__ import annotations

from typing import Optional

from ..domain.enums import OpportunityState, Priority, Qualification

FIT_A_MIN = 70
FIT_B_MIN = 40
BEHAVIOUR_HOT_MIN = 70
BEHAVIOUR_WARM_MIN = 40

_MATRIX: dict[tuple[str, str], Priority] = {
    ("A", "hot"): Priority.HIGH,
    ("A", "warm"): Priority.HIGH,
    ("A", "cold"): Priority.MEDIUM,
    ("B", "hot"): Priority.HIGH,
    ("B", "warm"): Priority.MEDIUM,
    ("B", "cold"): Priority.LOW,
    ("C", "hot"): Priority.MEDIUM,
    ("C", "warm"): Priority.LOW,
    ("C", "cold"): Priority.LOW,
}


def fit_band(fit: int) -> str:
    if fit >= FIT_A_MIN:
        return "A"
    if fit >= FIT_B_MIN:
        return "B"
    return "C"


def behaviour_band(behaviour: int) -> str:
    if behaviour >= BEHAVIOUR_HOT_MIN:
        return "hot"
    if behaviour >= BEHAVIOUR_WARM_MIN:
        return "warm"
    return "cold"


def derive(
    fit: int,
    behaviour: int,
    qualification: Qualification = Qualification.QUALIFIED,
    *,
    withdrawn: bool = False,
    state: Optional[OpportunityState] = None,
) -> Priority:
    """Band the two axes into a sales priority.

    Anything not QUALIFIED is LOW regardless of its numbers: it is not in the sales
    queue, so it cannot outrank something that is. A conversation the customer has
    explicitly withdrawn from is LOW for the same reason — the opportunity may still
    be worth something later, which is what the Dormant/Lost state and re-engagement
    are for, but it is not competing for a representative's attention now.

    A Dormant/Lost opportunity is capped at MEDIUM rather than forced to LOW: it may
    well be worth reviving, so it should not be buried under every live LOW lead, but
    it is not the next call to make either, which is what an uncapped HIGH would
    imply for a fit/behaviour combination that predates its own dormancy.
    """
    if qualification is not Qualification.QUALIFIED:
        return Priority.LOW
    if withdrawn:
        return Priority.LOW
    banded = _MATRIX[(fit_band(fit), behaviour_band(behaviour))]
    if state is OpportunityState.DORMANT_LOST and banded is Priority.HIGH:
        return Priority.MEDIUM
    return banded
