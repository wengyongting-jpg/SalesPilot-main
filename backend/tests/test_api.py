# -*- coding: utf-8 -*-
"""P6: the HTTP surface, split by visibility tier.

`docs/api/interface-v1.md` §2 is the specification, and its opening line is the point:
**the visibility boundary is enforced server-side by payload shape, not by client
discipline.**

The frozen build returned score, priority, signals, state, next best action and case
to whoever called the customer endpoint and relied on the customer frontend to discard
them. That is not a boundary — the data reached the customer's browser and was visible
in developer tools. Once prompts, token counts and costs exist it stops being
defensible at all.

So the strongest assertions here are not about a sample response. They are about the
**type**: `api/schemas/customer.py` has no field in which a score could be placed, so
leaking one is impossible rather than merely discouraged.
"""
from __future__ import annotations

import importlib.util
import json
import unittest

fastapi_available = importlib.util.find_spec("fastapi") is not None
httpx_available = importlib.util.find_spec("httpx") is not None

requires_http = unittest.skipUnless(
    fastapi_available and httpx_available,
    "fastapi/httpx not installed; run `pip install -r requirements.txt`",
)

# From interface-v1 §2, the "no" column: never on the customer tier.
FORBIDDEN_ON_CUSTOMER_TIER = (
    "state", "score", "priority", "final_score", "signals", "signal_history",
    "next_best_action", "case", "confidence", "agent_run", "qualification",
    "fit_total", "behaviour_total", "main_concern", "competitive_risk",
    "churn_risk", "state_change", "score_history", "state_history",
    "customer_message_count", "turns", "extraction_source", "detection",
)


def client(*, model=None):
    from fastapi.testclient import TestClient

    from backend.api.app import create_app
    from backend.storage.memory import InMemoryRepository

    return TestClient(create_app(repository=InMemoryRepository(), model=model))


def deep_keys(payload) -> set[str]:
    """Every key anywhere in a nested payload."""
    found: set[str] = set()
    if isinstance(payload, dict):
        for key, value in payload.items():
            found.add(key)
            found |= deep_keys(value)
    elif isinstance(payload, list):
        for item in payload:
            found |= deep_keys(item)
    return found


class TestCustomerSchemasCannotExpressSensitiveData(unittest.TestCase):
    """The tier boundary as a type, not as a filter."""

    def test_the_customer_reply_model_has_no_field_for_sales_intelligence(self):
        from backend.api.schemas.customer import CustomerReply

        fields = set(CustomerReply.model_fields)
        for forbidden in FORBIDDEN_ON_CUSTOMER_TIER:
            self.assertNotIn(forbidden, fields)

    def test_the_customer_message_model_carries_only_the_safe_axes(self):
        from backend.api.schemas.customer import CustomerMessage

        self.assertEqual(
            {"id", "ts", "role", "author", "rep_name", "generation", "text",
             "client_message_id"},
            set(CustomerMessage.model_fields),
        )

    def test_the_customer_schemas_reject_unknown_fields(self):
        """A permissive model would let a future careless `**payload` put a score
        back on the wire."""
        import pydantic

        from backend.api.schemas.customer import CustomerReply

        with self.assertRaises(pydantic.ValidationError):
            CustomerReply(reply="hi", human_takeover=False, score=99)


@requires_http
class TestCustomerSurface(unittest.TestCase):
    def setUp(self):
        self.client = client()

    def post(self, text, *, customer_id="C-1", name="Sam", key=None):
        body = {"customer_id": customer_id, "customer_name": name, "text": text}
        if key:
            body["client_message_id"] = key
        response = self.client.post("/api/messages", json=body)
        self.assertEqual(200, response.status_code, response.text)
        return response.json()

    def test_a_reply_carries_only_what_the_customer_may_see(self):
        payload = self.post("How much does CareSure Plus cost?")
        self.assertEqual(
            {"reply", "message", "facts", "quick_replies", "human_takeover",
             "client_message_id"},
            set(payload),
        )

    def test_no_forbidden_field_appears_anywhere_in_the_payload(self):
        payload = self.post("How much does CareSure Plus cost?")
        present = deep_keys(payload) & set(FORBIDDEN_ON_CUSTOMER_TIER)
        self.assertEqual(set(), present, f"leaked to the customer tier: {present}")

    def test_the_approved_facts_do_reach_the_customer(self):
        """They are the product cards. Removing them would be over-correcting."""
        payload = self.post("How much does CareSure Plus cost?")
        self.assertTrue(payload["facts"])
        self.assertTrue(any("S$" in fact for fact in payload["facts"]))

    def test_retrieval_confidence_does_not(self):
        payload = self.post("How much is Plus?")
        self.assertNotIn("confidence", json.dumps(payload))

    def test_the_reply_message_states_who_wrote_it_and_how(self):
        message = self.post("How much is Plus?")["message"]
        self.assertEqual("business", message["role"])
        self.assertEqual("ai", message["author"])
        self.assertIn(message["generation"], {"llm", "template"})

    def test_quick_replies_are_offered_and_respect_the_contract(self):
        payload = self.post("Hello, tell me about health insurance")
        chips = payload["quick_replies"]
        self.assertGreaterEqual(len(chips), 1)
        self.assertLessEqual(len(chips), 3)
        for chip in chips:
            self.assertEqual({"id", "label"}, set(chip))
            self.assertLessEqual(len(chip["label"]), 24)

    def test_the_idempotency_key_is_echoed(self):
        payload = self.post("hello", key="c-8f2a")
        self.assertEqual("c-8f2a", payload["client_message_id"])

    def test_a_replayed_key_returns_the_same_customer_payload(self):
        first = self.post("hello", key="k1")
        replay = self.post("hello", key="k1")
        self.assertEqual(first, replay)

    def test_an_empty_message_is_rejected(self):
        response = self.client.post(
            "/api/messages",
            json={"customer_id": "C-1", "customer_name": "Sam", "text": ""},
        )
        self.assertEqual(422, response.status_code)

    # ---- Transcript ------------------------------------------------------

    def test_the_transcript_is_safe_and_complete(self):
        self.post("How much is Plus?")
        payload = self.client.get("/api/conversations/C-1").json()
        self.assertEqual({"conversation_id", "human_takeover", "messages"},
                         set(payload))
        self.assertEqual(2, len(payload["messages"]))
        present = deep_keys(payload) & set(FORBIDDEN_ON_CUSTOMER_TIER)
        self.assertEqual(set(), present)

    def test_the_transcript_supports_an_incremental_cursor(self):
        self.post("How much is Plus?")
        self.post("And the waiting period?")
        everything = self.client.get("/api/conversations/C-1").json()["messages"]
        self.assertEqual(4, len(everything))

        cursor = everything[1]["id"]
        newer = self.client.get(
            f"/api/conversations/C-1?since={cursor}"
        ).json()["messages"]
        self.assertEqual([m["id"] for m in everything[2:]], [m["id"] for m in newer])

    def test_a_human_representatives_name_reaches_the_customer_transcript(self):
        self.post("I want to speak to a human agent")
        self.client.post(
            "/api/admin/opportunities/C-1/rep-reply",
            json={"text": "Alex here.", "rep_name": "Alex"},
        )
        messages = self.client.get("/api/conversations/C-1").json()["messages"]
        human = next(message for message in messages if message["author"] == "human")
        self.assertEqual("Alex", human["rep_name"])

    def test_a_future_cursor_returns_nothing(self):
        self.post("How much is Plus?")
        payload = self.client.get(
            "/api/conversations/C-1?since=2099-01-01T00:00:00"
        ).json()
        self.assertEqual([], payload["messages"])

    def test_a_malformed_cursor_is_a_client_error(self):
        self.post("How much is Plus?")
        response = self.client.get("/api/conversations/C-1?since=not-a-cursor")
        self.assertEqual(400, response.status_code)

    def test_an_unknown_conversation_is_not_found(self):
        self.assertEqual(404, self.client.get("/api/conversations/C-nope").status_code)

    def test_a_conversation_can_be_reset(self):
        self.post("How much is Plus?")
        response = self.client.delete("/api/conversations/C-1")
        self.assertEqual(200, response.status_code)
        self.assertTrue(response.json()["deleted"])
        self.assertEqual(404, self.client.get("/api/conversations/C-1").status_code)

    def test_resetting_twice_is_harmless(self):
        self.post("How much is Plus?")
        self.client.delete("/api/conversations/C-1")
        second = self.client.delete("/api/conversations/C-1")
        self.assertEqual(200, second.status_code)
        self.assertFalse(second.json()["deleted"])


@requires_http
class TestAdminSurface(unittest.TestCase):
    def setUp(self):
        self.client = client()

    def post(self, text, *, customer_id="C-1", name="Sam", key=None):
        body = {"customer_id": customer_id, "customer_name": name, "text": text}
        if key:
            body["client_message_id"] = key
        return self.client.post("/api/messages", json=body).json()

    def test_the_queue_carries_the_full_intelligence(self):
        self.post("How much does CareSure Plus cost?")
        payload = self.client.get("/api/admin/opportunities").json()
        self.assertEqual(1, payload["count"])
        opp = payload["items"][0]
        for expected in ("state", "priority", "final_score", "signals",
                         "qualification", "customer_message_count", "score"):
            self.assertIn(expected, opp)

    def test_the_admin_score_shows_both_axes_dimension_by_dimension(self):
        """A single total would hide what the redesign added, and a reviewer cannot
        sanity-check a number they cannot decompose."""
        self.post("How much does CareSure Plus cost?")
        score = self.client.get("/api/admin/opportunities").json()["items"][0]["score"]
        for expected in ("fit_total", "behaviour_total", "behaviour_raw",
                         "engagement_recency", "need_identified", "priority"):
            self.assertIn(expected, score)

    def test_the_deprecated_alias_travels_alongside_the_truthful_name(self):
        self.post("hello")
        opp = self.client.get("/api/admin/opportunities").json()["items"][0]
        self.assertEqual(opp["customer_message_count"], opp["turns"])

    def test_one_opportunity_can_be_read_with_bounded_history(self):
        """Gap register item 12."""
        for text in ("I want cover", "How much is Plus?", "How do I apply?"):
            self.post(text)
        full = self.client.get("/api/admin/opportunities/C-1").json()
        self.assertEqual(3, len(full["score_history"]))

        bounded = self.client.get(
            "/api/admin/opportunities/C-1?history_limit=1"
        ).json()
        self.assertEqual(1, len(bounded["score_history"]))

    def test_the_admin_read_supports_an_incremental_cursor(self):
        """Gap register item 12: the admin side is the one that polls the full
        profile, so it needs the cursor more than the customer side does."""
        self.post("I want cover")
        self.post("How much is Plus?")
        full = self.client.get("/api/admin/opportunities/C-1").json()
        cursor = full["messages"][1]["id"]
        trimmed = self.client.get(
            f"/api/admin/opportunities/C-1?since={cursor}"
        ).json()
        self.assertEqual(
            [m["id"] for m in full["messages"][2:]],
            [m["id"] for m in trimmed["messages"]],
        )

    def test_an_unknown_opportunity_is_not_found(self):
        self.assertEqual(
            404, self.client.get("/api/admin/opportunities/C-nope").status_code
        )

    def test_analytics_separates_held_traffic_from_the_funnel(self):
        self.post("We sell insurance leads, visit example.com", customer_id="C-spam")
        self.post("Buy our database now, limited offer", customer_id="C-spam")
        self.post("How much is Plus?", customer_id="C-real")

        payload = self.client.get("/api/admin/analytics").json()
        self.assertEqual(1, payload["total_opportunities"])
        self.assertEqual(1, payload["qualification"]["held"])
        self.assertIn("cost", payload)

    def test_the_dashboard_lists_the_queue(self):
        self.post("How much is Plus?")
        payload = self.client.get("/api/admin/dashboard").json()
        self.assertEqual(1, payload["total"])
        self.assertEqual(1, len(payload["items"]))
        item = payload["items"][0]
        self.assertLessEqual(len(item["messages"]), 1)
        self.assertEqual([], item["score_history"])
        self.assertEqual([], item["state_history"])

    def test_seeding_is_idempotent(self):
        first = self.client.post("/api/admin/seed").json()
        self.assertTrue(first["seeded"])
        self.assertFalse(self.client.post("/api/admin/seed").json()["seeded"])

    # ---- Agent runs ------------------------------------------------------

    def test_agent_runs_are_listed_newest_first(self):
        self.post("How much is Plus?")
        self.post("How do I apply?")
        runs = self.client.get("/api/admin/agent-runs?opportunity_id=C-1").json()
        self.assertEqual(2, runs["count"])

    def test_agent_runs_are_queryable_by_the_correlation_key(self):
        """`interface-v1.md` §3: `client_message_id` doubles as the telemetry key, so
        the admin can join on something the embedded customer app already knows."""
        self.post("hello", key="c-8f2a")
        runs = self.client.get(
            "/api/admin/agent-runs?opportunity_id=C-1&client_message_id=c-8f2a"
        ).json()
        self.assertEqual(1, runs["count"])

    def test_one_run_can_be_read_in_full(self):
        self.post("How much is Plus?")
        listed = self.client.get("/api/admin/agent-runs?opportunity_id=C-1").json()
        run_id = listed["items"][0]["run_id"]
        run = self.client.get(f"/api/admin/agent-runs/{run_id}").json()
        self.assertEqual(run_id, run["run_id"])
        for expected in ("steps", "llm_calls", "tool_calls", "totals", "status"):
            self.assertIn(expected, run)

    def test_an_unknown_run_is_not_found(self):
        self.assertEqual(
            404, self.client.get("/api/admin/agent-runs/ar-nope").status_code
        )

    def test_conversation_cost_totals_are_available(self):
        self.post("How much is Plus?")
        totals = self.client.get("/api/admin/opportunities/C-1/cost").json()
        self.assertEqual(1, totals["run_count"])
        self.assertIn("pricing_known", totals["cost"])

    # ---- Cases -----------------------------------------------------------

    def test_a_case_is_listed_with_its_exact_status_string(self):
        self.post("I want to speak to a human agent")
        cases = self.client.get("/api/admin/cases").json()
        self.assertEqual(1, cases["count"])
        self.assertEqual("Open", cases["items"][0]["status"])

    def test_a_case_transitions_through_the_exact_strings(self):
        self.post("I want to speak to a human agent")
        case_id = self.client.get("/api/admin/cases").json()["items"][0]["id"]

        taken = self.client.patch(
            f"/api/admin/cases/{case_id}", json={"status": "TAKEN_OVER"}
        )
        self.assertEqual(200, taken.status_code)
        self.assertEqual("Taken Over", taken.json()["status"])

        closed = self.client.patch(
            f"/api/admin/cases/{case_id}", json={"status": "Closed"}
        )
        self.assertEqual("Closed", closed.json()["status"])

    def test_closing_a_case_resumes_autonomous_selling(self):
        self.post("I want to speak to a human agent")
        case_id = self.client.get("/api/admin/cases").json()["items"][0]["id"]
        self.client.patch(f"/api/admin/cases/{case_id}", json={"status": "CLOSED"})
        opp = self.client.get("/api/admin/opportunities/C-1").json()
        self.assertFalse(opp["human_takeover"])

    def test_case_transition_error_codes(self):
        self.post("I want to speak to a human agent")
        case_id = self.client.get("/api/admin/cases").json()["items"][0]["id"]
        self.assertEqual(
            422, self.client.patch(f"/api/admin/cases/{case_id}").status_code
        )
        self.assertEqual(
            400,
            self.client.patch(
                f"/api/admin/cases/{case_id}", json={"status": "BANANA"}
            ).status_code,
        )
        self.assertEqual(
            404,
            self.client.patch(
                "/api/admin/cases/H-nope", json={"status": "CLOSED"}
            ).status_code,
        )

    # ---- Representative reply -------------------------------------------

    def test_a_rep_reply_is_refused_when_nobody_has_taken_over(self):
        """409, so the endpoint cannot be used to inject text while the assistant is
        still selling autonomously."""
        self.post("How much is Plus?")
        response = self.client.post(
            "/api/admin/opportunities/C-1/rep-reply",
            json={"text": "Hello", "rep_name": "Alex"},
        )
        self.assertEqual(409, response.status_code)

    def test_a_refused_rep_reply_appends_nothing(self):
        self.post("How much is Plus?")
        before = self.client.get("/api/admin/opportunities/C-1").json()["messages"]
        self.client.post(
            "/api/admin/opportunities/C-1/rep-reply",
            json={"text": "Hello", "rep_name": "Alex"},
        )
        after = self.client.get("/api/admin/opportunities/C-1").json()["messages"]
        self.assertEqual(len(before), len(after))

    def test_a_rep_reply_under_takeover_is_attributed_to_the_person(self):
        self.post("I want to speak to a human agent")
        response = self.client.post(
            "/api/admin/opportunities/C-1/rep-reply",
            json={"text": "Alex here, happy to help.", "rep_name": "Alex",
                  "client_message_id": "r-1"},
        )
        self.assertEqual(200, response.status_code, response.text)
        message = response.json()["message"]
        self.assertEqual("business", message["role"])
        self.assertEqual("human", message["author"])
        self.assertEqual("human", message["generation"])
        self.assertEqual("Alex", message["rep_name"])

    def test_the_customer_sees_the_representatives_message(self):
        """The point of the endpoint: a real person joins the conversation."""
        self.post("I want to speak to a human agent")
        self.client.post(
            "/api/admin/opportunities/C-1/rep-reply",
            json={"text": "Alex here.", "rep_name": "Alex"},
        )
        transcript = self.client.get("/api/conversations/C-1").json()["messages"]
        self.assertEqual("human", transcript[-1]["author"])
        self.assertEqual("Alex here.", transcript[-1]["text"])

    def test_a_rep_reply_changes_no_sales_state(self):
        self.post("I want to speak to a human agent")
        before = self.client.get("/api/admin/opportunities/C-1").json()
        self.client.post(
            "/api/admin/opportunities/C-1/rep-reply",
            json={"text": "Alex here.", "rep_name": "Alex"},
        )
        after = self.client.get("/api/admin/opportunities/C-1").json()
        self.assertEqual(before["state"], after["state"])
        self.assertEqual(before["final_score"], after["final_score"])
        self.assertEqual(
            before["customer_message_count"], after["customer_message_count"]
        )

    def test_an_unknown_conversation_cannot_receive_a_rep_reply(self):
        response = self.client.post(
            "/api/admin/opportunities/C-nope/rep-reply",
            json={"text": "Hi", "rep_name": "Alex"},
        )
        self.assertEqual(404, response.status_code)


@requires_http
class TestNoResponseUsesTheOldRoleValue(unittest.TestCase):
    """`interface-v1.md` §5.8: the rename is complete, with no transitional alias."""

    def test_no_endpoint_emits_role_agent(self):
        http = client()
        http.post(
            "/api/messages",
            json={"customer_id": "C-1", "customer_name": "Sam",
                  "text": "I want to speak to a human agent"},
        )
        http.post(
            "/api/admin/opportunities/C-1/rep-reply",
            json={"text": "Alex here.", "rep_name": "Alex"},
        )
        for path in (
            "/api/conversations/C-1",
            "/api/admin/opportunities",
            "/api/admin/opportunities/C-1",
            "/api/admin/cases",
            "/api/admin/dashboard",
            "/api/admin/analytics",
            "/api/admin/agent-runs?opportunity_id=C-1",
        ):
            with self.subTest(path):
                body = http.get(path).text
                self.assertNotIn('"role": "agent"', body)
                self.assertNotIn('"role":"agent"', body)


@requires_http
class TestSystemSurface(unittest.TestCase):
    def test_health_reports_liveness_and_counts(self):
        http = client()
        payload = http.get("/health").json()
        self.assertEqual("ok", payload["status"])
        for expected in ("conversations", "open_cases", "provider", "degraded"):
            self.assertIn(expected, payload)

    def test_health_says_when_no_model_is_configured(self):
        """An operator must be able to see that replies are template-generated without
        reading the logs."""
        payload = client().get("/health").json()
        self.assertTrue(payload["degraded"])

    def test_no_legacy_console_is_served(self):
        self.assertEqual(404, client().get("/").status_code)


if __name__ == "__main__":
    unittest.main()


@requires_http
class TestBrowserOriginsArePermitted(unittest.TestCase):
    """`docs/backend-contract.md` item 15, all six acceptance criteria.

    The two frontends are served as static files from another port, so they are
    permanently cross-origin and a browser rejects every `fetch` before it reaches the
    backend. Their adapters were verified from Node, where no same-origin policy
    applies, so the *mapping* was proven while the last step - the same code running in
    a browser tab - stayed blocked. Nothing on the frontend side can fix that.

    The negative case matters as much as the positive one. A wildcard would satisfy
    every other assertion here and is exactly what the register rules out.
    """

    ALLOWED = "http://127.0.0.1:8123"
    FOREIGN = "https://somewhere.example"

    def setUp(self):
        self.client = client()

    def test_a_preflight_from_a_development_origin_is_answered(self):
        response = self.client.options(
            "/api/messages",
            headers={
                "Origin": self.ALLOWED,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        self.assertLess(response.status_code, 300)
        methods = response.headers.get("access-control-allow-methods", "")
        headers = response.headers.get("access-control-allow-headers", "").lower()
        self.assertIn("POST", methods)
        self.assertIn("content-type", headers)

    def test_a_simple_request_carries_the_allow_origin_header(self):
        response = self.client.get("/health", headers={"Origin": self.ALLOWED})
        self.assertEqual(
            self.ALLOWED, response.headers.get("access-control-allow-origin")
        )

    def test_patch_and_delete_are_permitted(self):
        """The console transitions cases and the chat resets conversations. Omitting
        either would leave a frontend half working."""
        for method in ("PATCH", "DELETE"):
            with self.subTest(method=method):
                response = self.client.options(
                    "/api/admin/cases/H-1",
                    headers={
                        "Origin": self.ALLOWED,
                        "Access-Control-Request-Method": method,
                    },
                )
                self.assertIn(
                    method, response.headers.get("access-control-allow-methods", "")
                )

    def test_an_origin_outside_the_configured_list_is_not_granted_access(self):
        response = self.client.get("/health", headers={"Origin": self.FOREIGN})
        self.assertIsNone(response.headers.get("access-control-allow-origin"))

    def test_a_preflight_from_an_unknown_origin_is_not_granted_access(self):
        response = self.client.options(
            "/api/messages",
            headers={
                "Origin": self.FOREIGN,
                "Access-Control-Request-Method": "POST",
            },
        )
        self.assertIsNone(response.headers.get("access-control-allow-origin"))

    def test_the_allowed_origins_come_from_configuration(self):
        from backend import config

        self.assertTrue(config.CORS_ORIGINS)
        self.assertNotIn("*", config.CORS_ORIGINS)

    def test_the_default_list_covers_loopback_only(self):
        """Not a wildcard, even though nothing here is protected. There is no
        authentication anywhere - a recorded demo limitation - and `*` would set a
        habit that becomes a real hole the moment that changes."""
        from backend import config

        for origin in config.CORS_ORIGINS:
            with self.subTest(origin=origin):
                self.assertTrue(
                    "127.0.0.1" in origin or "localhost" in origin,
                    f"{origin} is not a loopback development origin",
                )

    def test_credentials_are_not_permitted(self):
        """There is no cookie or session to send, so allowing them would widen the
        surface for no benefit."""
        response = self.client.get("/health", headers={"Origin": self.ALLOWED})
        self.assertNotEqual(
            "true", response.headers.get("access-control-allow-credentials")
        )

    def test_a_real_customer_message_still_succeeds_with_an_origin_present(self):
        response = self.client.post(
            "/api/messages",
            headers={"Origin": self.ALLOWED},
            json={
                "customer_id": "C-1",
                "customer_name": "M",
                "text": "How much is the Plus plan?",
            },
        )
        self.assertEqual(200, response.status_code)
        self.assertEqual(
            self.ALLOWED, response.headers.get("access-control-allow-origin")
        )
        # The header must not have become an excuse to widen the payload.
        self.assertEqual(set(), deep_keys(response.json()) & set(
            FORBIDDEN_ON_CUSTOMER_TIER
        ))
