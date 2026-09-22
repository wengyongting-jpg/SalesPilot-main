# -*- coding: utf-8 -*-
"""FastAPI service layer tests (skipped automatically if FastAPI is absent)."""
import importlib.util
import shutil
import sys
import tempfile
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

    # ---- P0-5: message idempotency --------------------------------------

    def _post(self, customer_id, text, key=None, name="Idem"):
        body = {"customer_id": customer_id, "customer_name": name, "text": text}
        if key is not None:
            body["client_message_id"] = key
        response = self.client.post("/api/messages", json=body)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_p0_5_replayed_key_does_not_mutate_state(self):
        """P0-5: replaying a client_message_id must not re-run the pipeline.

        The failure mode this guards is silent, not an exception. `turns` is
        incremented unconditionally in handle_message, and the engagement
        dimension is min(12, 3 + 2 * turns) in engine/scoring.py, so a duplicate
        write inflates the opportunity value score for an event that never
        happened. A customer could be promoted toward HIGH priority by a flaky
        connection, with no error anywhere to notice.

        Acceptance criteria 1, 2 and 5 from docs/backend-contract.md Part B item 1.
        """
        first = self._post("C-9001", "hello", "k1")
        replay = self._post("C-9001", "hello", "k1")

        # AC1 — same turn count and same transcript length
        self.assertEqual(first["opportunity"]["turns"],
                         replay["opportunity"]["turns"])
        self.assertEqual(len(first["opportunity"]["messages"]),
                         len(replay["opportunity"]["messages"]))
        self.assertEqual(first["opportunity"]["turns"], 1)
        self.assertEqual(len(first["opportunity"]["messages"]), 2)

        # AC2 — identical score and state transition
        self.assertEqual(first["score"]["total"], replay["score"]["total"])
        self.assertEqual(first["state_change"], replay["state_change"])

        # AC5 — no extra score_history entry from the replay
        self.assertEqual(len(replay["opportunity"]["score_history"]), 1)

        # Stronger than the stated criteria: the whole response is replayed
        # verbatim, so no field can drift between the two calls.
        self.assertEqual(first, replay)

    def test_p0_5_different_key_same_text_still_advances(self):
        """P0-5 / AC3: a new key is a new message, even with identical text.

        Deduplication must key on the client's idempotency key alone. Collapsing
        on message text instead would silently swallow a customer legitimately
        repeating themselves.
        """
        first = self._post("C-9002", "hello", "k1")
        second = self._post("C-9002", "hello", "k2")
        self.assertEqual(first["opportunity"]["turns"], 1)
        self.assertEqual(second["opportunity"]["turns"], 2)
        self.assertEqual(len(second["opportunity"]["messages"]), 4)

    def test_p0_5_omitting_the_key_preserves_original_behaviour(self):
        """P0-5 / AC4: without a key the endpoint behaves exactly as before."""
        first = self._post("C-9003", "hello")
        second = self._post("C-9003", "hello")
        self.assertEqual(first["opportunity"]["turns"], 1)
        self.assertEqual(second["opportunity"]["turns"], 2)
        self.assertEqual(len(second["opportunity"]["score_history"]), 2)

    def test_p0_5_key_is_echoed_on_the_stored_message(self):
        """P0-5: `client_message_id` round-trips on the customer message.

        The customer chat reconciles a locally queued message against the
        server transcript. Echoing the key lets it match exactly instead of
        matching by position from the end of the array. Agent replies carry null.
        """
        body = self._post("C-9004", "hello", "k-echo")
        messages = body["opportunity"]["messages"]
        self.assertEqual(messages[0]["role"], "customer")
        self.assertEqual(messages[0]["client_message_id"], "k-echo")
        self.assertEqual(messages[1]["role"], "agent")
        self.assertIsNone(messages[1]["client_message_id"])

        # A message sent without a key serialises the field as null, never absent
        plain = self._post("C-9005", "hello")
        self.assertIn("client_message_id", plain["opportunity"]["messages"][0])
        self.assertIsNone(plain["opportunity"]["messages"][0]["client_message_id"])

    def test_p0_5_blank_customer_id_is_not_deduplicated(self):
        """P0-5: with no customer_id there is no conversation to deduplicate in.

        The backend generates a fresh opportunity id, so two such calls are two
        distinct conversations even when they share a key. Documented under
        'As implemented' in the contract so a client knows it must supply its own
        customer_id to get idempotency on the very first message.
        """
        first = self._post("", "hello", "k-blank")
        second = self._post("", "hello", "k-blank")
        self.assertNotEqual(first["opportunity"]["opportunity_id"],
                            second["opportunity"]["opportunity_id"])
        self.assertEqual(self.client.get("/api/opportunities").json()["count"], 2)

    def test_case_status_patch_rejects_an_invalid_body(self):
        """U1 (extended): the PATCH request model and its status codes.

        The admin console updates its view from the response body rather than
        from the value it requested, so the failure modes need to stay distinct:
        a malformed request is 422, an unknown status value is 400, and an
        unknown case is 404.
        """
        self.client.post(
            "/api/messages",
            json={"customer_id": "C-BAD", "customer_name": "Casey",
                  "text": "I want to speak to a human agent"},
        )
        case_id = self.client.get("/api/cases").json()["items"][0]["id"]

        self.assertEqual(self.client.patch(f"/api/cases/{case_id}").status_code, 422)
        self.assertEqual(
            self.client.patch(f"/api/cases/{case_id}", json={}).status_code, 422
        )
        self.assertEqual(
            self.client.patch(f"/api/cases/{case_id}", json={"status": ""}).status_code,
            422,
        )
        self.assertEqual(
            self.client.patch(
                f"/api/cases/{case_id}", json={"status": "BANANA"}
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.patch(
                "/api/cases/H-NOPE", json={"status": "CLOSED"}
            ).status_code,
            404,
        )
        # A rejected request must not have changed anything
        self.assertEqual(
            self.client.get("/api/cases").json()["items"][0]["status"], "Open"
        )

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


@unittest.skipUnless(
    fastapi_available and httpx_available,
    "fastapi/httpx not installed; run `pip install -r requirements.txt`",
)
class TestIdempotencyPersistence(unittest.TestCase):
    """P0-5: deduplication must survive a process restart under SQLite.

    A retry usually happens because the client never saw the response. If the
    server was restarted in between — which is exactly what a deploy or a crash
    looks like — an in-memory-only receipt would be gone and the retry would
    inflate `turns` again. The contract requires the key to be stored alongside
    the message, so this is the regression test for that requirement.
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = Path(self.tmpdir) / "idempotency.db"

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _client_on_a_fresh_process(self):
        """A new repository + app, as if the server had just been restarted."""
        from fastapi.testclient import TestClient

        from salespilot.agent import SalesPilotAgent
        from salespilot.api import create_app
        from salespilot.storage.sqlite_repo import SqliteRepository

        repo = SqliteRepository(self.db_path)
        return TestClient(create_app(agent=SalesPilotAgent(repository=repo))), repo

    def test_receipt_survives_a_restart(self):
        payload = {
            "customer_id": "C-DB",
            "customer_name": "Persist",
            "text": "How much does CareSure Plus cost?",
            "client_message_id": "k-restart",
        }

        client, repo = self._client_on_a_fresh_process()
        first = client.post("/api/messages", json=payload).json()
        repo.close()

        client, repo = self._client_on_a_fresh_process()
        replay = client.post("/api/messages", json=payload).json()

        self.assertEqual(first, replay)
        self.assertEqual(replay["opportunity"]["turns"], 1)
        self.assertEqual(len(replay["opportunity"]["messages"]), 2)

        # The key is persisted on the message itself, not only in the receipt
        stored = repo.get_opportunity("C-DB")
        self.assertEqual(stored.messages[0].client_message_id, "k-restart")
        self.assertIsNone(stored.messages[1].client_message_id)
        repo.close()


class TestSerialisedEnumContracts(unittest.TestCase):
    """U5-U8: lock the serialised enum strings the frontends switch on.

    These run without FastAPI on purpose. The serializers in api/schemas.py emit
    `enum.value` verbatim, so the enum definitions *are* the wire contract. The
    frontends have no build step and no type checking, so a rename here would
    reach them as silently wrong labels rather than as an error. U1 already
    guards case status; this extends the same pattern to the other four rows of
    the table in docs/backend-handoff.md section 4.
    """

    def test_u5_opportunity_state_strings(self):
        """U5: the six state strings, exact, including the punctuated two."""
        from salespilot.models import OpportunityState

        self.assertEqual(
            [s.value for s in OpportunityState],
            [
                "Cold Lead",
                "Potential Interest",
                "Evaluation & Hesitation",
                "High Intent",
                "Closed / Active Customer",
                "Dormant / Lost",
            ],
        )

    def test_u6_priority_strings(self):
        """U6: priority is uppercase; badge and count logic depends on it."""
        from salespilot.models import Priority

        self.assertEqual([p.value for p in Priority], ["HIGH", "MEDIUM", "LOW"])

    def test_u7_product_strings(self):
        """U7: product ids are lowercase; label maps and product cards key on them."""
        from salespilot.models import Product

        self.assertEqual(
            [p.value for p in Product],
            ["essential", "family", "plus", "corporate", "unknown"],
        )

    def test_u8_signal_strings(self):
        """U8: the 11 signals, including the 'Expansion: Family' colon-space form."""
        from salespilot.models import Signal

        self.assertEqual(
            [s.value for s in Signal],
            [
                "Purchase",
                "Purchase Preparation",
                "Hesitation",
                "Competitive",
                "Expansion: Family",
                "Expansion: Corporate",
                "Human Request",
                "Compliance Risk",
                "Negotiation",
                "Conversion",
                "Withdrawal",
            ],
        )

    def test_u5_u6_survive_the_analytics_aggregation(self):
        """U5/U6 on a real consumer path, not just the enum definition.

        /api/analytics rebuilds `by_state`, `funnel` and `by_priority` from the
        enums, so it is where a rename would actually surface. The admin queue
        reads these keys directly.
        """
        from salespilot.analytics import compute_analytics
        from salespilot.storage import Repository

        analytics = compute_analytics(Repository())
        self.assertEqual(
            list(analytics["by_state"].keys()),
            [
                "Cold Lead",
                "Potential Interest",
                "Evaluation & Hesitation",
                "High Intent",
                "Closed / Active Customer",
                "Dormant / Lost",
            ],
        )
        self.assertEqual(
            [entry["state"] for entry in analytics["funnel"]],
            list(analytics["by_state"].keys()),
            "funnel and by_state must agree, and stay in funnel order",
        )
        self.assertEqual(
            list(analytics["by_priority"].keys()), ["HIGH", "MEDIUM", "LOW"]
        )


@unittest.skipUnless(
    fastapi_available and httpx_available,
    "fastapi/httpx not installed; run `pip install -r requirements.txt`",
)
class TestSerialisedEnumContractsOverHttp(unittest.TestCase):
    """U7-U8 over the wire: the exact strings a live response actually carries."""

    def setUp(self):
        from fastapi.testclient import TestClient

        from salespilot.agent import SalesPilotAgent
        from salespilot.api import create_app
        from salespilot.storage import Repository

        self.client = TestClient(create_app(agent=SalesPilotAgent(repository=Repository())))

    def test_u7_product_is_lowercase_over_the_wire(self):
        body = self.client.post(
            "/api/messages",
            json={"customer_id": "C-U7", "customer_name": "U7",
                  "text": "How much does CareSure Plus cost?"},
        ).json()
        self.assertEqual(body["detection"]["product"], "plus")
        self.assertEqual(body["opportunity"]["product"], "plus")
        self.assertEqual(body["retrieval"]["product"], "plus")

    def test_u8_signal_values_are_emitted_verbatim(self):
        body = self.client.post(
            "/api/messages",
            json={"customer_id": "C-U8", "customer_name": "U8",
                  "text": "I want to speak to a human agent"},
        ).json()
        self.assertIn("Human Request", body["detection"]["signals"])
        self.assertIn("Human Request", body["opportunity"]["signals"])
        self.assertIn("Human Request", body["opportunity"]["signal_history"])

    def test_u8_expansion_signals_keep_the_colon_space_form(self):
        """The seeded demo data exercises both expansion signals.

        `/api/analytics` returns signal *names* as dictionary keys, so this is
        the path where the colon-space form would break a frontend label map.
        """
        self.assertTrue(self.client.post("/api/seed").json()["seeded"])
        signals = self.client.get("/api/analytics").json()["signals"]
        self.assertIn("Expansion: Family", signals)
        self.assertIn("Expansion: Corporate", signals)
        for name in signals:
            if name.startswith("Expansion"):
                self.assertTrue(
                    name.startswith("Expansion: "),
                    f"Expansion signals must use the colon-space form, got {name!r}",
                )


if __name__ == "__main__":
    unittest.main()
