# -*- coding: utf-8 -*-
"""Vector store abstraction with an in-memory cosine-similarity default.

A real deployment can implement the same interface on top of a hosted vector
database (pgvector, OpenSearch, a managed vector service, ...) without
changing the retrieval layer.
"""
from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class VectorRecord:
    id: str
    vector: list[float]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ScoredRecord:
    record: VectorRecord
    score: float


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        raise ValueError("Vectors must have the same dimension")
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class VectorStore(ABC):
    @abstractmethod
    def add(self, records: list[VectorRecord]) -> None: ...

    @abstractmethod
    def query(
        self,
        vector: list[float],
        k: int = 5,
        filter_fn: Optional[Callable[[dict[str, Any]], bool]] = None,
    ) -> list[ScoredRecord]: ...


class InMemoryVectorStore(VectorStore):
    def __init__(self) -> None:
        self._records: dict[str, VectorRecord] = {}

    def add(self, records: list[VectorRecord]) -> None:
        for record in records:
            self._records[record.id] = record

    def count(self) -> int:
        return len(self._records)

    def query(
        self,
        vector: list[float],
        k: int = 5,
        filter_fn: Optional[Callable[[dict[str, Any]], bool]] = None,
    ) -> list[ScoredRecord]:
        candidates = list(self._records.values())
        if filter_fn is not None:
            candidates = [r for r in candidates if filter_fn(r.metadata)]
        scored = [
            ScoredRecord(record=r, score=cosine_similarity(vector, r.vector))
            for r in candidates
        ]
        scored.sort(key=lambda item: item.score, reverse=True)
        return scored[:k]
