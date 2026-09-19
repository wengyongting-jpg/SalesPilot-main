# -*- coding: utf-8 -*-
"""Pluggable AI provider interfaces.

The decision engine never calls an LLM directly. External AI capabilities are
hidden behind three narrow interfaces so they can be swapped without touching
agent orchestration:

- LLMClient:      chat-style text generation
- Embedder:       text -> vector
- VectorStore:    add / upsert / similarity search over vectors

Offline defaults (stub LLM, hashing embedder, in-memory cosine store) keep the
whole system runnable with zero API keys and zero third-party packages.
"""
from .embeddings import Embedder, LocalHashingEmbedder
from .llm import (
    LLMClient,
    StubLLMClient,
    UnavailableLLMError,
    build_llm_client,
)
from .vectorstore import InMemoryVectorStore, VectorStore

__all__ = [
    "LLMClient",
    "StubLLMClient",
    "UnavailableLLMError",
    "build_llm_client",
    "Embedder",
    "LocalHashingEmbedder",
    "VectorStore",
    "InMemoryVectorStore",
]
