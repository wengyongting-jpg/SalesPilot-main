# -*- coding: utf-8 -*-
"""Semantic knowledge retriever built on the provider interfaces.

This is the "real RAG" shape from the spec (section 7): knowledge-base
documents are chunked, embedded and indexed in a vector store; each customer
question is embedded and matched by vector similarity.

It is deliberately hybrid so the demo stays reliable offline:
- intent-routed authoritative fields (e.g. premium for a price question) are
  always included as grounded facts, guaranteeing an approved answer;
- vector similarity adds the most relevant extra chunks and drives the
  confidence signal;
- fully unanswerable queries (no field route and no meaningful similarity)
  get low confidence so the HITL layer can escalate instead of guessing.

Swap LocalHashingEmbedder / InMemoryVectorStore for model-backed
implementations and nothing else in the agent has to change.
"""
from typing import Optional

from ..models import Intent, Product, RetrievalResult
from ..providers import Embedder, InMemoryVectorStore, LocalHashingEmbedder, VectorStore
from ..providers.vectorstore import VectorRecord
from .retriever import (
    FIELD_LABELS,
    INTENT_FIELDS,
    KnowledgeRetriever,
    load_knowledge_base,
)

# Knowledge-base fields indexed as searchable chunks
_CHUNK_FIELDS = (
    "positioning",
    "target_customer",
    "eligibility",
    "coverage",
    "premium",
    "deductible",
    "limits",
    "waiting_period",
    "exclusions",
    "claims",
    "payment",
    "renewal",
)


class SemanticKnowledgeRetriever(KnowledgeRetriever):
    """Vector-index retriever with the same public interface as the rule version."""

    def __init__(
        self,
        kb: Optional[dict] = None,
        embedder: Optional[Embedder] = None,
        store: Optional[VectorStore] = None,
        similarity_threshold: float = 0.1,
    ) -> None:
        super().__init__(kb=kb)
        self.embedder = embedder or LocalHashingEmbedder()
        self.store = store or InMemoryVectorStore()
        self.similarity_threshold = similarity_threshold
        self._index()

    # ---- Indexing --------------------------------------------------------

    def _index(self) -> None:
        records: list[VectorRecord] = []
        for product in self.kb["products"]:
            product_id = product["id"]
            for field_name in _CHUNK_FIELDS:
                if field_name not in product:
                    continue
                label = FIELD_LABELS.get(field_name, field_name)
                text = str(product[field_name])
                chunk = f"{product['name']} {label}. {text}"
                records.append(
                    VectorRecord(
                        id=f"{product_id}:{field_name}",
                        vector=self.embedder.embed(chunk),
                        metadata={
                            "product_id": product_id,
                            "field": field_name,
                            "label": label,
                            "text": text,
                        },
                    )
                )
            for index, item in enumerate(product.get("faq", [])):
                chunk = f"{product['name']} FAQ. {item['q']} {item['a']}"
                records.append(
                    VectorRecord(
                        id=f"{product_id}:faq:{index}",
                        vector=self.embedder.embed(chunk),
                        metadata={
                            "product_id": product_id,
                            "field": "faq",
                            "label": "FAQ",
                            "text": f"{item['q']} {item['a']}",
                        },
                    )
                )
        self.store.add(records)

    # ---- Retrieval -------------------------------------------------------

    def retrieve(
        self,
        query: str,
        product: Product = Product.UNKNOWN,
        intent: Intent = Intent.GENERIC,
    ) -> RetrievalResult:
        if product == Product.UNKNOWN:
            return self._product_overview(intent, query)

        product_data = self.products[product.value]
        preferred = [
            f
            for f in INTENT_FIELDS.get(intent, ("positioning",))
            if f in product_data and f != "positioning"
        ]

        facts: list[str] = [
            f"{product_data['name']}: {product_data['positioning']}"
        ]
        seen_fields: set[str] = {"positioning"}

        # 1) Authoritative fields routed by intent (grounding guarantee)
        for field_name in preferred:
            label = FIELD_LABELS.get(field_name, field_name)
            facts.append(f"{label}: {product_data[field_name]}")
            seen_fields.add(field_name)

        # 2) Vector similarity over this product's chunks
        query_vector = self.embedder.embed(query)
        hits = self.store.query(
            query_vector,
            k=5,
            filter_fn=lambda meta: meta["product_id"] == product.value,
        )
        strong_hits = [h for h in hits if h.score >= self.similarity_threshold]
        for hit in strong_hits:
            meta = hit.record.metadata
            if meta["field"] in seen_fields:
                continue
            if meta["field"] == "faq":
                facts.append(f"FAQ - {meta['text']}")
            else:
                facts.append(f"{meta['label']}: {meta['text']}")
            seen_fields.add(meta["field"])

        # 3) FAQ also benefits from vector similarity
        #    (already included via field == "faq" above)

        top_score = strong_hits[0].score if strong_hits else 0.0
        confidence = self._confidence(bool(preferred), top_score)
        return RetrievalResult(
            facts=facts,
            matches=[
                type(self)._to_match(h, product.value) for h in strong_hits
            ],
            confidence=confidence,
            product=product,
        )

    @staticmethod
    def _to_match(hit, product_id: str):
        from ..models import KnowledgeMatch

        return KnowledgeMatch(
            product_id=product_id,
            field=hit.record.metadata["field"],
            snippet=hit.record.metadata["text"],
            score=int(hit.score * 100),
        )

    @staticmethod
    def _confidence(has_preferred: bool, top_similarity: float) -> float:
        if has_preferred:
            # Authoritative field available: trustworthy, similarity refines it
            if top_similarity >= 0.35:
                return 0.95
            if top_similarity >= 0.15:
                return 0.9
            return 0.8
        # No routed field: rely on vector evidence alone
        if top_similarity >= 0.35:
            return 0.75
        if top_similarity >= 0.15:
            return 0.55
        return 0.3
