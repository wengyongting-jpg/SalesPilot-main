# -*- coding: utf-8 -*-
"""Provider interfaces and the offline semantic RAG retriever tests."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from salespilot.knowledge import SemanticKnowledgeRetriever
from salespilot.models import Intent, Product
from salespilot.providers import (
    InMemoryVectorStore,
    LocalHashingEmbedder,
    StubLLMClient,
    UnavailableLLMError,
)
from salespilot.providers.vectorstore import VectorRecord, cosine_similarity


class TestProviders(unittest.TestCase):
    def test_hashing_embedder_is_deterministic_and_normalised(self):
        embedder = LocalHashingEmbedder(dim=128)
        a = embedder.embed("private hospital coverage")
        b = embedder.embed("private hospital coverage")
        self.assertEqual(a, b)
        self.assertAlmostEqual(sum(x * x for x in a) ** 0.5, 1.0, places=6)

    def test_vector_store_ranks_matching_chunk_first(self):
        embedder = LocalHashingEmbedder()
        store = InMemoryVectorStore()
        store.add([
            VectorRecord("a", embedder.embed("family spouse children premium")),
            VectorRecord("b", embedder.embed("corporate employees SME group")),
        ])
        hits = store.query(embedder.embed("insurance for our employees"), k=1)
        self.assertEqual(hits[0].record.id, "b")
        self.assertGreater(hits[0].score, 0.0)
        self.assertLessEqual(cosine_similarity(embedder.embed("x"), embedder.embed("y")), 1.0)

    def test_stub_llm_raises(self):
        with self.assertRaises(UnavailableLLMError):
            StubLLMClient().generate([{"role": "user", "content": "hi"}])


class TestSemanticRetriever(unittest.TestCase):
    def setUp(self):
        self.retriever = SemanticKnowledgeRetriever()

    def test_index_built(self):
        # 4 products x 12 fields + 4 FAQs
        self.assertGreaterEqual(self.retriever.store.count(), 50)

    def test_price_query_grounded_and_confident(self):
        result = self.retriever.retrieve(
            "what is the premium price?", Product.PLUS, Intent.PRICE
        )
        joined = "\n".join(result.facts)
        self.assertIn("S$1,500", joined)
        self.assertGreaterEqual(result.confidence, 0.8)

    def test_corporate_question_returns_corporate_facts(self):
        result = self.retriever.retrieve(
            "cover for employees in my company",
            Product.CORPORATE,
            Intent.CORPORATE_NEED,
        )
        joined = "\n".join(result.facts)
        self.assertIn("SME", joined)

    def test_unknown_product_overview(self):
        result = self.retriever.retrieve("hello", Product.UNKNOWN, Intent.GENERIC)
        self.assertEqual(result.confidence, 0.9)
        self.assertGreaterEqual(len(result.facts), 4)


if __name__ == "__main__":
    unittest.main()
