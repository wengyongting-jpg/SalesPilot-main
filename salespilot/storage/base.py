# -*- coding: utf-8 -*-
"""Repository abstraction shared by the in-memory and SQLite implementations."""
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from ..models import HumanCase, Opportunity


class BaseRepository(ABC):
    # ---- Opportunities ---------------------------------------------------

    @abstractmethod
    def upsert_opportunity(self, opp: Opportunity) -> None: ...

    @abstractmethod
    def get_opportunity(self, opp_id: str) -> Optional[Opportunity]: ...

    @abstractmethod
    def list_opportunities(self) -> list[Opportunity]: ...

    @abstractmethod
    def delete_opportunity(self, opp_id: str) -> None: ...

    # ---- HITL cases ------------------------------------------------------

    @abstractmethod
    def add_case(self, case: HumanCase) -> None: ...

    def update_case(self, case: HumanCase) -> None:
        """Update a case (status transition). Default: same as add_case."""
        self.add_case(case)

    @abstractmethod
    def list_cases(self) -> list[HumanCase]: ...

    # ---- Optional persistence hook --------------------------------------

    def save(self, path: Optional[Path] = None) -> Path:  # pragma: no cover
        raise NotImplementedError("This repository does not support JSON export")
