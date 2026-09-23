# -*- coding: utf-8 -*-
"""P7: model access — the same conversation, with and without a model.

Acceptance from `docs/backend-plan.md` §9 P7:

    1. With no key configured, a full conversation completes, every business
       message reports `generation: "template"`, and each run reports
       `status: "degraded"`.
    2. With a key configured, the same conversation reports
       `generation: "llm"` and `status: "ok"`.

`TestModel` stands in for "a key configured": what is under test is that the
pipeline reports honestly which path it took, not the quality of any model's
output.
"""
from __future__ import annotations

import unittest

from pydantic_ai.models.test import TestModel

from backend import config
from backend.agent.extraction import build_extractor
from backend.agent.reply import build_composer
from backend.domain.enums import Generation
from backend.providers.probe import probe
from backend.services.conversation import ConversationService
from backend.storage import MemoryRepository

CONVERSATION = [
    "Hi! I'm looking for health insurance with private hospital coverage.",
    "How much does CareSure Plus cost?",
    "What does it cover?",
]


def _service(extraction_model=None, reply_model=None) -> ConversationService:
    return ConversationService(
        MemoryRepository(),
        extractor=build_extractor(extraction_model),
        composer=build_composer(reply_model),
    )


class _Quiet(unittest.TestCase):
    def setUp(self):
        self._trace, self._provider = config.CONSOLE_TRACE, config.LLM_PROVIDER
        config.CONSOLE_TRACE = False

    def tearDown(self):
        config.CONSOLE_TRACE, config.LLM_PROVIDER = self._trace, self._provider

    def run_conversation(self, service) -> list:
        return [
            service.handle_customer_message("C-1", "Sarah", text, client_message_id=f"k{i}")
            for i, text in enumerate(CONVERSATION)
        ]


class TestOfflinePath(_Quiet):
    def test_a_full_conversation_completes_as_template_and_degraded(self):
        service = _service()
        results = self.run_conversation(service)

        self.assertEqual(len(results), len(CONVERSATION))
        for result in results:
            self.assertEqual(result.reply.generation, Generation.TEMPLATE)
            self.assertEqual(result.run.status, "degraded")
            self.assertEqual(result.run.totals()["llm_call_count"], 0)
            self.assertTrue(result.run.degraded_reasons)

        opportunity = service.repo.get_opportunity("C-1")
        business = [m for m in opportunity.messages if not m.is_from_customer]
        self.assertEqual(len(business), len(CONVERSATION))
        self.assertTrue(all(m.generation is Generation.TEMPLATE for m in business))
        # And it is visible on the stored runs, not only in memory.
        self.assertTrue(all(r["status"] == "degraded" for r in service.repo.list_runs()))

    def test_the_probe_reports_offline_rather_than_failing(self):
        config.LLM_PROVIDER = "offline"
        result = probe()
        self.assertEqual(result["provider"], "offline")
        self.assertIsNone(result["reachable"])
        self.assertIn("offline", result["detail"])


class TestModelBackedPath(_Quiet):
    def test_the_same_conversation_reports_llm_and_ok(self):
        service = _service(
            # The default TestModel calls every registered tool, including the
            # handover proposal; restrict extraction to a read-only lookup.
            extraction_model=TestModel(call_tools=["lookup_product_fact"]),
            reply_model=TestModel(),
        )
        results = self.run_conversation(service)

        for result in results:
            self.assertEqual(result.reply.generation, Generation.LLM)
            self.assertEqual(result.run.status, "ok")
            self.assertEqual(result.run.degraded_reasons, [])
            self.assertGreaterEqual(result.run.totals()["llm_call_count"], 2)
            self.assertEqual(result.extraction_source, "llm")

        business = [m for m in service.repo.get_opportunity("C-1").messages if not m.is_from_customer]
        self.assertTrue(all(m.generation is Generation.LLM for m in business))
