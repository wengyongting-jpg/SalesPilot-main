# -*- coding: utf-8 -*-
"""Priority: derived from both axes as a matrix, never by thresholding one number.

Specification: `docs/v0.0/backend/backend-contract.md` gap register item 13.

The wire values are unchanged — `HIGH`, `MEDIUM`, `LOW` — so badge and count logic
in the admin console is unaffected. Only the derivation changes.

Why a matrix rather than a threshold on a combined total: averaging the two axes
first destroys the distinction that made separating them worthwhile. A conversation
with no fit and frantic activity averages to the same number as a good fit with
moderate activity, and those two need opposite treatment. The matrix keeps them
apart:

                            behaviour
    fit          hot (>=70)   warm (>=40)   cold (<40)
    A (>=75)     HIGH         HIGH          MEDIUM
    B (>=40)     HIGH         MEDIUM        LOW
    C (<40)      MEDIUM       LOW           LOW

Reading the bottom-left cell is the point: strong behaviour with no fit reaches
MEDIUM at most. That is the spam case, and on the frozen build it reached HIGH.

Three conditions cap the result regardless of the two axes, because in each of them
the conversation has already been established not to be live:

    not qualified   it is not in the sales queue, so it cannot outrank something that
                    is
    withdrawn       the customer said no
    dormant or lost the state machine has concluded the conversation has stalled

The last of those was missing and showed up end to end: a customer who said "let me
think about it" reached Dormant/Lost and still came out HIGH, because priority read
the two axes and never the state. A representative's next call should not be to
somebody who has just asked for time.
"""
from __future__ import annotations

from typing import Optional

from ..domain.enums import OpportunityState, Priority, Qualification

# Band A means a clearly valuable, well-identified opportunity. 75 rather than 70
# because a single question naming a mid-tier plan scores exactly 70 (need 40 +
# product 30), and that came out HIGH when the API was first run end to end. HIGH means
# "call this person now"; awarding it on one message devalues the band and refills the
# queue with everything, which is the undifferentiated state this redesign exists to
# fix. A larger opportunity still reaches A: Corporate is 80, and a mid-tier plan with
# a family expansion is 83.
FIT_A_MIN = 75
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
    """Band the two axes into a sales priority, then apply the caps.

    A dormant or lost opportunity is capped at MEDIUM rather than forced to LOW: it
    may well be worth reviving, which is exactly what the state and a re-engagement
    follow-up are for. It simply is not the next call to make.
    """
    if qualification is not Qualification.QUALIFIED:
        return Priority.LOW
    if withdrawn:
        return Priority.LOW

    banded = _MATRIX[(fit_band(fit), behaviour_band(behaviour))]

    if state is OpportunityState.DORMANT_LOST and banded is Priority.HIGH:
        return Priority.MEDIUM
    return banded
