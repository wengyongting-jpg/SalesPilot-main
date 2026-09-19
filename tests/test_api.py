# -*- coding: utf-8 -*-
"""FastAPI service layer tests (skipped automatically if FastAPI is absent)."""
import importlib.util
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

fastapi_available = importlib.util.find_spec("fastapi") is not None
httpx_available = importlib.util.find_spec("httpx") is not None


@unittest.skipUnless(
    fastapi_available and httpx_available,
    "fastapi/httpx not installed; run `pip install -r requirements.txt`",
)
class TestApi(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient

        from salespilot.agent import SalesPilotAgent
        from salespilot.api import create_app
        from salespilot.storage import Repository

        self.agent = SalesPilotAgent(repository=Repository())
        self.client = TestClient(create_app(agent=self.agent))

    def test_health(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_message_workflow_and_opportunity(self):
        response = self.client.post(
            "/api/messages",
            json={
                "customer_id": "C-API",
                "customer_name": "Api Customer",
                "text": "How much does CareSure Plus cost?",
            },
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("S$1,500", body["reply"])
        self.assertEqual(body["opportunity"]["product"], "plus")
        self.assertIsNotNone(body["score"]["total"])

        listing = self.client.get("/api/opportunities")
        self.assertEqual(listing.json()["count"], 1)

        detail = self.client.get("/api/opportunities/C-API")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["customer_name"], "Api Customer")

        self.assertEqual(self.client.get("/api/opportunities/nope").status_code, 404)

    def test_escalation_creates_case(self):
        self.client.post(
            "/api/messages",
            json={
                "customer_id": "C-H",
                "customer_name": "Hans",
                "text": "I have a pre-existing heart condition, is it covered?",
            },
        )
        cases = self.client.get("/api/cases").json()
        self.assertGreaterEqual(cases["count"], 1)
        self.assertIn("underwriting", cases["items"][0]["reason"].lower())

    def test_seed_analytics_dashboard(self):
        seeded = self.client.post("/api/seed").json()
        self.assertTrue(seeded["seeded"])
        self.assertEqual(seeded["customers_seeded"], 3)
        # Idempotent: second call does nothing
        again = self.client.post("/api/seed").json()
        self.assertFalse(again["seeded"])

        analytics = self.client.get("/api/analytics").json()
        self.assertEqual(analytics["total_opportunities"], 3)
        self.assertEqual(analytics["by_priority"]["HIGH"], 2)

        dashboard = self.client.get("/api/dashboard").json()
        self.assertIn("SALES DASHBOARD", dashboard["text"])
        self.assertEqual(dashboard["total"], 3)

    def test_validation_error_on_empty_message(self):
        response = self.client.post(
            "/api/messages",
            json={"customer_id": "", "customer_name": "X", "text": ""},
        )
        self.assertEqual(response.status_code, 422)

    def test_case_status_contract(self):
        """U1: lock the case-status strings the frontend depends on.

        The API must serialize case status as 'Open' / 'Taken Over' / 'Closed'
        and the PATCH endpoint must transition through those exact values. The
        frontend normalizes these tokens; this test guards the contract.
        """
        # Trigger a HITL case (explicit human request)
        self.client.post(
            "/api/messages",
            json={
                "customer_id": "C-CASE",
                "customer_name": "Casey",
                "text": "I want to speak to a human agent",
            },
        )
        cases = self.client.get("/api/cases").json()
        self.assertGreaterEqual(cases["count"], 1)
        case = cases["items"][0]
        # Exact serialized value the frontend must match
        self.assertEqual(case["status"], "Open")
        case_id = case["id"]

        # PATCH OPEN -> TAKEN_OVER
        r1 = self.client.patch(
            f"/api/cases/{case_id}", json={"status": "TAKEN_OVER"}
        )
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r1.json()["status"], "Taken Over")

        # PATCH TAKEN_OVER -> CLOSED
        r2 = self.client.patch(
            f"/api/cases/{case_id}", json={"status": "CLOSED"}
        )
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.json()["status"], "Closed")

        # Confirm persisted value is the exact string
        after = self.client.get("/api/cases").json()["items"][0]
        self.assertEqual(after["status"], "Closed")


if __name__ == "__main__":
    unittest.main()
