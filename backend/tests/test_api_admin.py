# -*- coding: utf-8 -*-
"""P6: the admin surface, and the two acceptance checks that live there.

    2. `rep-reply` returns 409 when the opportunity is not under takeover,
       and appends nothing.
    3. A rep reply serialises as `role: "business"`, `author: "human"`,
       `generation: "human"`.
    4. No response anywhere contains `"role": "agent"` — walked across every
       endpoint in `TestNoResponseSaysAgent`.
"""
from __future__ import annotations

import json
import unittest

from fastapi.testclient import TestClient

from backend import config
from backend.api.app import create_app
from backend.storage import MemoryRepository


class _ApiCase(unittest.TestCase):
    def setUp(self):
        self._trace, self._content = config.CONSOLE_TRACE, config.TELEMETRY_CONTENT
        config.CONSOLE_TRACE = False
        self.client = TestClient(create_app(MemoryRepository()))

    def tearDown(self):
        config.CONSOLE_TRACE, config.TELEMETRY_CONTENT = self._trace, self._content

    def send(self, text, *, customer_id="C-1", key=None):
        body = {"customer_id": customer_id, "customer_name": "Sarah", "text": text}
        if key:
            body["client_message_id"] = key
        return self.client.post("/api/messages", json=body)

    def escalate(self):
        self.send("How much does CareSure Plus cost?", key="k1")
        return self.send("Can you give me a discount?", key="k2").json()


class TestOpportunities(_ApiCase):
    def test_list_and_get_carry_the_full_intelligence(self):
        self.send("How much does CareSure Plus cost?", key="k1")
        listing = self.client.get("/api/admin/opportunities").json()
        self.assertEqual(listing["count"], 1)
        row = listing["items"][0]
        self.assertEqual(row["turns"], row["customer_message_count"])
        self.assertIn(row["priority"], {"HIGH", "MEDIUM", "LOW"})

        body = self.client.get("/api/admin/opportunities/C-1").json()
        for key in ("state", "score", "fit", "behaviour", "qualification", "signals", "signal_history",
                    "score_history", "state_history", "messages", "next_best_action", "case",
                    "customer_message_count", "turns"):
            self.assertIn(key, body)
        self.assertEqual(body["turns"], body["customer_message_count"])
        # `total` is the display-only rounded mean of the two axes.
        mean = (body["fit"]["total"] + body["behaviour"]["total"]) / 2
        self.assertLessEqual(abs(body["score"]["total"] - mean), 0.5)
        self.assertEqual(set(body["messages"][0]), {"id", "ts", "role", "author", "generation", "text", "client_message_id", "rep_name"})
        self.assertIsNone(body["case"])
        self.assertEqual(set(body["next_best_action"]), {"action", "reason", "priority", "human_intervention_required"})

    def test_history_limit_bounds_the_arrays_and_since_filters_messages(self):
        for i in range(4):
            self.send(f"Message {i} about the Plus plan", key=f"k{i}")
        body = self.client.get("/api/admin/opportunities/C-1?history_limit=2").json()
        self.assertEqual(len(body["score_history"]), 2)
        self.assertEqual(body["history_limit"], 2)
        first_id = body["messages"][0]["id"]
        newer = self.client.get(f"/api/admin/opportunities/C-1?since={first_id}").json()["messages"]
        self.assertEqual(len(newer), 7)
        self.assertEqual(self.client.get("/api/admin/opportunities/C-1?since=bad").status_code, 400)
        self.assertEqual(self.client.get("/api/admin/opportunities/nope").status_code, 404)

    def test_the_active_case_is_embedded_after_escalation(self):
        self.escalate()
        body = self.client.get("/api/admin/opportunities/C-1").json()
        self.assertIsNotNone(body["case"])
        self.assertEqual(body["case"]["status"], "Open")
        self.assertTrue(body["human_takeover"])

    def test_legacy_paths_answer_as_aliases(self):
        self.send("Hi", key="k1")
        self.assertEqual(self.client.get("/api/opportunities").json()["count"], 1)
        self.assertEqual(self.client.get("/api/opportunities/C-1").status_code, 200)
        self.assertEqual(self.client.get("/api/cases").json()["count"], 0)
        self.assertEqual(self.client.get("/api/analytics").status_code, 200)
        self.assertEqual(set(self.client.get("/api/dashboard").json()), {"text", "total", "take_over", "items"})
        self.assertEqual(self.client.delete("/api/opportunities/C-1").json()["deleted"], True)


class TestCases(_ApiCase):
    def test_patch_status_codes_and_the_closed_rule(self):
        self.escalate()
        case_id = self.client.get("/api/admin/cases").json()["items"][0]["id"]

        self.assertEqual(self.client.patch(f"/api/admin/cases/{case_id}", json={}).status_code, 422)
        self.assertEqual(self.client.patch(f"/api/admin/cases/{case_id}", json={"status": "resolved"}).status_code, 400)
        self.assertEqual(self.client.patch("/api/admin/cases/H-NOPE", json={"status": "CLOSED"}).status_code, 404)

        taken = self.client.patch(f"/api/admin/cases/{case_id}", json={"status": "taken over"})
        self.assertEqual((taken.status_code, taken.json()["status"]), (200, "Taken Over"))
        closed = self.client.patch(f"/api/admin/cases/{case_id}", json={"status": "CLOSED"}).json()
        self.assertEqual(closed["status"], "Closed")
        opp = self.client.get("/api/admin/opportunities/C-1").json()
        self.assertFalse(opp["human_takeover"])
        self.assertFalse(opp["human_intervention_required"])
        self.assertIsNone(opp["case"])


class TestRepReply(_ApiCase):
    def test_409_when_not_under_takeover_and_nothing_appended(self):
        self.send("Hi", key="k1")
        before = len(self.client.get("/api/admin/opportunities/C-1").json()["messages"])
        response = self.client.post("/api/admin/opportunities/C-1/rep-reply", json={"text": "Hello", "rep_name": "Ana"})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(len(self.client.get("/api/admin/opportunities/C-1").json()["messages"]), before)

    def test_under_takeover_it_serialises_as_business_human_human(self):
        self.escalate()
        response = self.client.post(
            "/api/admin/opportunities/C-1/rep-reply",
            json={"text": "Hi Sarah, Ana here.", "rep_name": "Ana", "client_message_id": "r-1"},
        )
        self.assertEqual(response.status_code, 200)
        message = response.json()["message"]
        self.assertEqual((message["role"], message["author"], message["generation"]), ("business", "human", "human"))
        self.assertEqual(message["rep_name"], "Ana")
        # And the customer sees it on their next poll, as a human message.
        transcript = self.client.get("/api/conversations/C-1").json()["messages"]
        self.assertEqual((transcript[-1]["author"], transcript[-1]["generation"]), ("human", "human"))
        self.assertEqual(self.client.post("/api/admin/opportunities/nope/rep-reply", json={"text": "x"}).status_code, 404)


class TestAgentRuns(_ApiCase):
    def test_runs_by_both_keys_and_by_id(self):
        self.send("Hi there", key="k1")
        self.send("How much does CareSure Plus cost?", key="k2")
        by_opp = self.client.get("/api/admin/agent-runs?opportunity_id=C-1").json()
        self.assertEqual(by_opp["count"], 2)
        by_key = self.client.get("/api/admin/agent-runs?client_message_id=k2").json()
        self.assertEqual(by_key["count"], 1)
        run = by_key["items"][0]
        self.assertEqual(set(run), {
            "run_id", "opportunity_id", "client_message_id", "trigger", "customer_message_count",
            "started_at", "finished_at", "duration_ms", "status", "steps", "llm_calls", "tool_calls", "totals",
        })
        self.assertEqual(self.client.get(f"/api/admin/agent-runs/{run['run_id']}").json()["run_id"], run["run_id"])
        self.assertEqual(self.client.get("/api/admin/agent-runs/ar-nope").status_code, 404)
        self.assertEqual(self.client.get("/api/admin/agent-runs?limit=1").json()["count"], 1)

    def test_content_flag_is_reported(self):
        config.TELEMETRY_CONTENT = False
        self.send("Hi", key="k1")
        self.assertFalse(self.client.get("/api/admin/agent-runs").json()["content_enabled"])


class TestQualificationActionsAndSeed(_ApiCase):
    def test_disqualify_release_and_held(self):
        self.send("Hi", key="k1")
        out = self.client.post("/api/admin/opportunities/C-1/disqualify", json={"reason": "Duplicate"}).json()
        self.assertEqual(out["qualification"], "disqualified")
        out = self.client.post("/api/admin/opportunities/C-1/release").json()
        self.assertEqual(out["qualification"], "qualified")
        self.assertEqual(self.client.post("/api/admin/opportunities/nope/release").status_code, 404)

        spam = "Check out our limited time offer, click here to grow your business"
        self.send(spam, customer_id="C-9")
        self.send(spam, customer_id="C-9")
        held = self.client.get("/api/admin/held").json()
        self.assertEqual([o["opportunity_id"] for o in held["items"]], ["C-9"])

    def test_seed_is_idempotent(self):
        self.assertTrue(self.client.post("/api/admin/seed").json()["seeded"])
        self.assertFalse(self.client.post("/api/seed").json()["seeded"])
        self.assertEqual(self.client.get("/health").json()["opportunities"], 3)


class TestNoResponseSaysAgent(_ApiCase):
    """Acceptance 4: no response anywhere contains `"role": "agent"`."""

    def test_every_endpoint(self):
        self.client.post("/api/admin/seed")
        self.escalate()
        self.client.post("/api/admin/opportunities/C-1/rep-reply", json={"text": "Ana here", "rep_name": "Ana"})
        run_id = self.client.get("/api/admin/agent-runs?limit=1").json()["items"][0]["run_id"]
        case_id = self.client.get("/api/admin/cases").json()["items"][0]["id"]

        responses = [
            self.client.get("/health"),
            self.send("Anything else?", key="k3"),
            self.client.get("/api/conversations/C-1"),
            self.client.get("/api/admin/opportunities"),
            self.client.get("/api/admin/opportunities/C-1"),
            self.client.get("/api/admin/opportunities/C-1024"),
            self.client.get("/api/admin/cases"),
            self.client.patch(f"/api/admin/cases/{case_id}", json={"status": "TAKEN_OVER"}),
            self.client.get("/api/admin/dashboard"),
            self.client.get("/api/admin/analytics"),
            self.client.get("/api/admin/agent-runs"),
            self.client.get(f"/api/admin/agent-runs/{run_id}"),
            self.client.get("/api/admin/held"),
        ]
        for response in responses:
            self.assertEqual(response.status_code, 200, response.url)
            text = json.dumps(response.json())
            self.assertNotIn('"role": "agent"', text, response.url)
            for role in _roles(response.json()):
                self.assertIn(role, {"customer", "business"}, response.url)


def _roles(payload) -> list[str]:
    found: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key == "role" and isinstance(value, str):
                found.append(value)
            found += _roles(value)
    elif isinstance(payload, list):
        for item in payload:
            found += _roles(item)
    return found
