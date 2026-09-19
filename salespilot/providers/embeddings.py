# -*- coding: utf-8 -*-
"""Embedding provider abstraction with an offline default.

LocalHashingEmbedder turns text into a deterministic hashed bag-of-words
vector (unigrams + bigrams, L2-normalised). It has no semantic model behind it,
but it gives the semantic retrieval layer a real vector index that runs fully
offline and is stable across processes. Swap it for a model-backed Embedder
(e.g. an embeddings API) without touching the retriever.
"""
from __future__ import annotations

import hashlib
import math
import re
from abc import ABC, abstractmethod

from .. import config

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _features(text: str) -> list[str]:
    tokens = [
        token
        for token in _TOKEN_RE.findall(text.lower())
        if len(token) > 1
    ]
    bigrams = [f"{a}_{b}" for a, b in zip(tokens, tokens[1:])]
    return tokens + bigrams


def _hash_dim(feature: str, dim: int) -> int:
    digest = hashlib.md5(feature.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % dim


class Embedder(ABC):
    dim: int

    @abstractmethod
    def embed(self, text: str) -> list[float]:
        """Return an L2-normalised embedding vector for `text`."""
        raise NotImplementedError

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(text) for text in texts]


class LocalHashingEmbedder(Embedder):
    """Deterministic offline embedder (hashing trick + cosine-friendly norm)."""

    def __init__(self, dim: int | None = None) -> None:
        self.dim = dim or config.LOCAL_EMBED_DIM

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        for feature in _features(text):
            vector[_hash_dim(feature, self.dim)] += 1.0
        norm = math.sqrt(sum(value * value for value in vector))
        if norm > 0:
            vector = [value / norm for value in vector]
        return vector
