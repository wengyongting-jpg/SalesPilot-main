# -*- coding: utf-8 -*-
"""Liveness. Served to both tiers; carries counts only."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ...services import analytics
from ...storage.base import Repository
from ..deps import get_repo

router = APIRouter()


@router.get("/health")
def health(repo: Repository = Depends(get_repo)) -> dict:
    return analytics.health(repo)
