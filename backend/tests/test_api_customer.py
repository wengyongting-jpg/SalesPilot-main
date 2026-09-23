# -*- coding: utf-8 -*-
"""P6: the customer surface — `interface-v1.md` §5.1, §5.5, §5.6.

Acceptance (docs/backend-plan.md §9 P6, check 1): every field in the §2
"no" column is absent from the customer response — verified against the
response keys, recursively, not by reading the code.
"""
from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from backend import config
from backend.api.app import create_app
from backend.storage import MemoryRepository

# interface-v1 §2 "no" column, contract item 6, plus every telemetry key.
FORBIDDEN_KEYS = {
    "state", "score", "final_score", "priority", "signals", "signal_history",
    "next_best_action", "case", "detection", "confidence", "retrieval",
    "run", "run_id", "agent_run", "steps", "llm_calls", "tool_calls",
    "tokens", "total_tokens", "cost", "fit", "behaviour", "qualification",
    "opportunity", "score_history", "state_history", "extraction_source",
    "state_change", "score_total",
}
CUSTOMER_REPLY_KEYS = {
    "reply", "generation", "product", "facts", "quick_replies", "client_message_id", "human_takeover",
}
TRANSCRIPT_MESSAGE_KEYS = {"id", "ts", "role", "author", "generation", "text", "client_message_id"}


def _keys(payload) -> set[str]:
    found: set[str] = set()
    if isinstance(payload, dict):
        for key, value in payload.items():
            found.add(key)
            found |= _keys(value)
    elif isinstance(payload, list):
        for item in payload:
            found |= _keys(item)
    return found


class _ApiCase(unittest.TestCase):
    def setUp(self):
        self._trace = config.CONSOLE_TRACE
        config.CONSOLE_TRACE = False
        self.client = TestClient(create_app(MemoryRepository()))

    def tearDown(self):
        config.CONSOLE_TRACE = self._trace

    def send(self, text, *, customer_id="C-1", key=None, name="Sarah"):
        body = {"customer_id": customer_id, "customer_name": name, "text": text}
        if key:
            body["client_message_id"] = key
        return self.client.post("/api/messages", json=body)


class TestPostMessage(_ApiCase):
    def test_response_has_exactly_the_customer_keys_and_none_of_the_forbidden_ones(self):
        response = self.send("How much does CareSure Plus cost?", key="k1")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body), CUSTOMER_REPLY_KEYS)
        self.assertEqual(_keys(body) & FORBIDDEN_KEYS, set())
        self.assertEqual(body["client_message_id"], "k1")
        self.assertEqual(body["generation"], "template")
        self.assertTrue(body["facts"])

    def test_forbidden_fields_stay_absent_after_an_escalation(self):
        """The turn that opens a case is the one most tempted to leak the reason."""
        self.send("How much does CareSure Plus cost?")
        body = self.send("Can you give me a discount?").json()
        self.assertTrue(body["human_takeover"])
        self.assertEqual(_keys(body) & FORBIDDEN_KEYS, set())
        self.assertEqual(body["quick_replies"], [])

    def test_no_query_parameter_or_header_leaks_telemetry(self):
        response = self.client.post(
            "/api/messages?include=telemetry&debug=1",
            json={"customer_id": "C-1", "customer_name": "Sarah", "text": "Hi"},
            headers={"X-Debug": "1", "X-Tier": "admin"},
        )
        self.assertEqual(_keys(response.json()) & FORBIDDEN_KEYS, set())

    def test_replay_returns_the_same_body_and_advances_nothing(self):
        first = self.send("How much does CareSure Plus cost?", key="k1").json()
        again = self.send("How much does CareSure Plus cost?", key="k1").json()
        self.assertEqual(first, again)
        self.assertEqual(len(self.client.get("/api/conversations/C-1").json()["messages"]), 2)

    def test_quick_replies_obey_the_contract(self):
        chips = self.send("Hi, I'm looking for health insurance.").json()["quick_replies"]
        self.assertTrue(1 <= len(chips) <= 3)
        for chip in chips:
            self.assertEqual(set(chip), {"id", "label"})
            self.assertLessEqual(len(chip["label"]), 24)

    def test_validation(self):
        self.assertEqual(self.client.post("/api/messages", json={"customer_name": "S"}).status_code, 422)
        self.assertEqual(self.client.post("/api/messages", json={"customer_name": "S", "text": ""}).status_code, 422)

    def test_blank_customer_id_is_assigned_one_server_side(self):
        response = self.send("Hello", customer_id="")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get("/health").json()["opportunities"], 1)


class TestTranscript(_ApiCase):
    def test_safe_transcript_shape(self):
        self.send("How much does CareSure Plus cost?", key="k1")
        body = self.client.get("/api/conversations/C-1").json()
        self.assertEqual(set(body), {"opportunity_id", "human_takeover", "messages"})
        self.assertEqual(len(body["messages"]), 2)
        for message in body["messages"]:
            self.assertEqual(set(message), TRANSCRIPT_MESSAGE_KEYS)
            self.assertIn(message["role"], {"customer", "business"})
        customer, business = body["messages"]
        self.assertEqual((customer["author"], customer["generation"], customer["client_message_id"]), (None, None, "k1"))
        self.assertEqual((business["author"], business["generation"]), ("ai", "template"))
        self.assertEqual(_keys(body) & FORBIDDEN_KEYS, set())

    def test_since_by_message_id_and_by_timestamp(self):
        self.send("Hi there")
        self.send("How much does CareSure Plus cost?")
        messages = self.client.get("/api/conversations/C-1").json()["messages"]
        self.assertEqual(len(messages), 4)
        after_first = self.client.get(f"/api/conversations/C-1?since={messages[0]['id']}").json()["messages"]
        self.assertEqual([m["id"] for m in after_first], [m["id"] for m in messages[1:]])
        after_last_ts = self.client.get(f"/api/conversations/C-1?since={messages[-1]['ts']}").json()["messages"]
        self.assertEqual(after_last_ts, [])
        self.assertEqual(self.client.get("/api/conversations/C-1?since=2099-01-01T00:00:00").json()["messages"], [])

    def test_bad_cursor_is_400_and_unknown_id_is_404(self):
        self.send("Hi")
        self.assertEqual(self.client.get("/api/conversations/C-1?since=not-a-cursor").status_code, 400)
        self.assertEqual(self.client.get("/api/conversations/nope").status_code, 404)
        self.assertEqual(self.client.get("/api/conversations/nope").json(), {"detail": "Opportunity not found: nope"})


class TestReset(_ApiCase):
    def test_delete_is_idempotent(self):
        self.send("Hi")
        self.assertEqual(self.client.delete("/api/conversations/C-1").json(), {"deleted": True, "opportunity_id": "C-1"})
        self.assertEqual(self.client.delete("/api/conversations/C-1").json()["deleted"], False)
        self.assertEqual(self.client.get("/api/conversations/C-1").status_code, 404)
