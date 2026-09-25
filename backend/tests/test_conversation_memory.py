from __future__ import annotations

import json
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from backend.agent.extraction import model_based
from backend.agent.tools import ToolContext
from backend.agent.tools.opportunity import search_conversation_history
from backend.domain.conversation_memory import ConversationMemory
from backend.domain.enums import OpportunityState, Product
from backend.domain.message import Message
from backend.domain.opportunity import Opportunity
from backend.knowledge import loader
from backend.observability import RunRecorder
from backend.agent.extraction import build_extractor
from backend.agent.reply import build_composer
from backend import config
from backend.services.conversation import ConversationService
from backend.storage import InMemoryRepository
from pydantic_ai.models.test import TestModel


class _SummaryAgent:
    output = None
    error = None

    def __init__(self, *args, **kwargs):
        pass

    def run_sync(self, *args, **kwargs):
        if self.error:
            raise self.error
        return SimpleNamespace(output=self.output, all_messages=lambda: [])


class TestConversationMemory(unittest.TestCase):
    def test_domain_codec_defaults_old_records_and_round_trips_sources(self):
        old = ConversationMemory.from_dict(None)
        self.assertEqual([], old.facts)
        self.assertIsNone(old.through_message_id)

        memory = ConversationMemory.from_dict({
            "version": 1,
            "facts": [{"text": "Prefers email", "source_message_ids": ["m-1"], "verification_status": "verified"}],
            "covered_message_ids": ["m-1"],
            "through_message_id": "m-2",
            "updated_at": "2026-09-25T10:00:00",
        })
        self.assertEqual("m-1", memory.facts[0].source_message_ids[0])
        self.assertEqual("m-2", memory.to_dict()["through_message_id"])
        self.assertEqual("unverified", memory.to_dict()["facts"][0]["verification_status"])

    def test_extraction_prompt_keeps_six_recent_messages_and_deduplicates_latest(self):
        history = [Message.from_customer(f"old message {i}", id=f"m-{i}") for i in range(12)]
        memory = {
            "facts": [{"text": "Needs private hospital cover", "source_message_ids": ["m-0"]}],
            "covered_message_ids": ["m-0"],
        }
        prompt = model_based._build_extraction_prompt("latest request", history, memory)

        self.assertIn("m-11", prompt)
        self.assertIn("m-7", prompt)
        self.assertNotIn("m-6", prompt)
        self.assertEqual(1, prompt.count("latest request"))
        self.assertIn("source message references: m-0", prompt)
        self.assertIn("UNVERIFIED recall note", prompt)
        self.assertIn("they do not prove the note", prompt)
        self.assertIn("search for the underlying detail with search_conversation_history", prompt)
        self.assertNotIn("score", prompt.lower())
        self.assertLessEqual(model_based._estimate_tokens(prompt), model_based._CONTEXT_TOKEN_BUDGET)

    def test_compaction_rejects_unknown_sources_and_tracks_the_processed_cursor(self):
        history = [Message.from_customer(f"message {i}", id=f"m-{i}") for i in range(8)]
        _SummaryAgent.output = model_based._MemorySummaryOutput(facts=[
            model_based._MemoryFactOutput(text="Needs a family plan", source_message_ids=["m-0"]),
            model_based._MemoryFactOutput(text="Unsupported", source_message_ids=["untrusted-id"]),
        ])
        _SummaryAgent.error = None
        try:
            with patch.object(model_based, "Agent", _SummaryAgent):
                packed, error = model_based._compact_memory(history, None, model=object(), recorder=None)
        finally:
            _SummaryAgent.output = None

        self.assertIsNone(error)
        self.assertEqual("m-2", packed["through_message_id"])
        self.assertEqual(["m-0"], packed["covered_message_ids"])
        self.assertEqual(["m-0"], packed["facts"][0]["source_message_ids"])
        self.assertEqual(1, len(packed["facts"]))

    def test_summary_failure_keeps_last_valid_memory(self):
        history = [Message.from_customer(f"message {i}", id=f"m-{i}") for i in range(8)]
        previous = {
            "version": 1,
            "facts": [{"text": "Existing fact", "source_message_ids": ["m-old"]}],
            "covered_message_ids": ["m-old"],
            "through_message_id": "m-old",
        }
        _SummaryAgent.error = RuntimeError("model failed")
        try:
            with patch.object(model_based, "Agent", _SummaryAgent):
                retained, error = model_based._compact_memory(
                    history, previous, model=object(), recorder=None
                )
        finally:
            _SummaryAgent.error = None

        self.assertEqual(previous, retained)
        self.assertIn("memory summary unavailable", error)

    def test_oversized_latest_message_degrades_before_sending_a_model_request(self):
        recorder = RunRecorder("C-1", content_enabled=False)
        outcome = model_based.extract(
            "x" * (model_based._MAX_LATEST_CHARS + 1),
            model=TestModel(),
            recorder=recorder,
        )

        self.assertEqual("rules", outcome.source)
        self.assertIn("context exceeds", outcome.unavailable)
        self.assertEqual([], recorder.llm_calls)

    def test_history_tool_caps_query_limit_and_snippet_size(self):
        context = ToolContext(
            kb=loader.load(),
            history_search=lambda query, limit: [
                {"message_id": "m-1", "role": "customer", "timestamp": "t", "text": "x" * 500}
                for _ in range(9)
            ],
        )
        result = json.loads(search_conversation_history(context, "  old   preference ", 50))

        self.assertEqual(5, len(result))
        self.assertEqual(320, len(result[0]["text"]))
        self.assertEqual("search_conversation_history", context.calls[0].name)

    def test_history_tool_without_bound_repository_returns_no_fabricated_results(self):
        context = ToolContext(kb=loader.load())
        result = search_conversation_history(context, "old detail")

        self.assertIn("unavailable", result)
        self.assertEqual(1, len(context.history_errors))

    def test_live_extractor_compacts_aged_history_and_persists_the_memory_cursor(self):
        old_trace = config.CONSOLE_TRACE
        config.CONSOLE_TRACE = False
        repository = InMemoryRepository()
        service = ConversationService(
            repository,
            extractor=build_extractor(TestModel(call_tools=[])),
            composer=build_composer(TestModel()),
            trace=False,
        )
        try:
            for index in range(4):
                result = service.handle_customer_message(
                    "C-1", "Sarah", f"Customer detail {index}", client_message_id=f"memory-{index}"
                )
            memory = repository.get_memory("C-1")
            purposes = [call.purpose for call in result.run.llm_calls]

            self.assertIsNotNone(memory)
            self.assertTrue(memory["through_message_id"])
            self.assertIn("memory_summary", purposes)
            saved_memory = dict(memory)
            replay = service.handle_customer_message(
                "C-1", "Sarah", "Customer detail 3", client_message_id="memory-3"
            )
            self.assertTrue(replay.replayed)
            self.assertEqual(saved_memory, repository.get_memory("C-1"))
        finally:
            config.CONSOLE_TRACE = old_trace

    def test_live_model_can_call_history_search_bound_to_current_opportunity(self):
        old_trace = config.CONSOLE_TRACE
        config.CONSOLE_TRACE = False
        repository = InMemoryRepository()
        opportunity = Opportunity(id="C-1", customer_name="Sarah")
        opportunity.messages.append(Message.from_customer("I prefer email contact", id="older-pref"))
        repository.upsert_opportunity(opportunity)
        service = ConversationService(
            repository,
            extractor=build_extractor(TestModel(call_tools=["search_conversation_history"])),
            composer=build_composer(TestModel()),
            trace=False,
        )
        original_search = repository.search_messages
        with patch.object(repository, "search_messages", wraps=original_search) as search:
            try:
                result = service.handle_customer_message(
                    "C-1", "Sarah", "What did I say before?", client_message_id="search-now"
                )
            finally:
                config.CONSOLE_TRACE = old_trace

        self.assertTrue(search.called)
        self.assertEqual("C-1", search.call_args.args[0])
        self.assertIn("search_conversation_history", [call.name for call in result.run.tool_calls])


if __name__ == "__main__":
    unittest.main()
