# -*- coding: utf-8 -*-
"""Knowledge layer: structured JSON knowledge base and retrieval backends."""
from .retriever import KnowledgeRetriever, load_knowledge_base
from .semantic import SemanticKnowledgeRetriever

__all__ = [
    "KnowledgeRetriever",
    "SemanticKnowledgeRetriever",
    "load_knowledge_base",
]
