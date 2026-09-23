# -*- coding: utf-8 -*-
"""P7: real model access, and the accounting that proves a call happened.

Three things are under test here, and the third is the reason this file exists.

1. **Configuration to spec.** `.env` precedence, secret redaction, and every way
   `resolve()` can decide there is no model - each with a reason a human can act on.
2. **Spec to wire.** `probe()` against a real HTTP server on localhost, so the
   endpoint construction, the Authorization header and the five outcome states are
   exercised for real rather than asserted against a mock of our own design.
3. **Cost accounting.** A model call that is not recorded makes the run report
   `llm_call_count: 0` and `cost: {"amount": 0.0, "pricing_known": true}` - not
   "unmeasured" but "measured, and free". That was live from P4 to P6. The suite was
   green throughout, because the recorder was tested without its caller and the only
   service-level assertion about the count ran on the offline path, where zero is the
   right answer. `TestModel` reports token usage, so the whole defect was catchable
   with no network, no key and no fake server. That is the lesson worth keeping: the
   gap was not a missing capability, it was a fixture that could not fail.
"""
from __future__ import annotations

import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory

from backend import config
from backend.providers import ProviderSpec, offline, probe, resolve
from backend.providers.probe import models as probe_models


# ---- A real OpenAI-compatible endpoint, on localhost ----------------------


class _FakeHandler(BaseHTTPRequestHandler):
    """Answers chat completions according to `server.behaviour`."""

    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        """Silence. The test runner's output is not a web server log."""

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) or b"{}"
        self.server.requests.append((self.path, dict(self.headers), json.loads(raw)))

        behaviour = self.server.behaviour
        if behaviour == "ok":
            status, payload = 200, {
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "choices": [{
                    "index": 0,
                    "message": {"role": "assistant", "content": "ok"},
                    "finish_reason": "stop",
                }],
                "usage": {
                    "prompt_tokens": 7, "completion_tokens": 2, "total_tokens": 9
                },
            }
        elif behaviour == "not_a_completion":
            # A proxy login page answering 200 at the API's URL. Reachable, useless.
            status, payload = 200, {"message": "please sign in"}
        elif behaviour == "unauthorized":
            status, payload = 401, {"error": {"message": "invalid_api_key"}}
        elif behaviour == "not_found":
            status, payload = 404, {"error": {"message": "model_not_found"}}
        else:
            status, payload = 429, {"error": {"message": "rate limit"}}

        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class _FakeEndpoint:
    """A context manager owning a real socket, so nothing here is mocked."""

    def __init__(self, behaviour: str = "ok") -> None:
        self.server = HTTPServer(("127.0.0.1", 0), _FakeHandler)
        self.server.behaviour = behaviour
        self.server.requests = []
        self.base_url = f"http://127.0.0.1:{self.server.server_port}/v1"

    def __enter__(self) -> "_FakeEndpoint":
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    @property
    def requests(self) -> list:
        return self.server.requests

    def spec(self, **overrides) -> ProviderSpec:
        return resolve(**{
            "provider": "gateway",
            "api_key": "sk-test-key",
            "base_url": self.base_url,
            "model_name": "test-model",
            "timeout": 10.0,
            **overrides,
        })


# ---- 1. Configuration ----------------------------------------------------


class TestEnvFile(unittest.TestCase):
    """`.env` is a convenience for local work, not an override of the environment."""

    def _load(self, text: str) -> tuple[list, dict]:
        with TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text(text, encoding="utf-8")
            before = dict(os.environ)
            try:
                applied = config.load_env_file(path)
                return applied, dict(os.environ)
            finally:
                os.environ.clear()
                os.environ.update(before)

    def test_a_real_environment_variable_is_never_overridden(self):
        """The failure this prevents: a key exported for one run being silently
        replaced by a stale line in a file somebody forgot about."""
        os.environ["SALESPILOT_TEST_KEY"] = "from-the-environment"
        try:
            applied, environment = self._load("SALESPILOT_TEST_KEY=from-the-file\n")
            self.assertNotIn("SALESPILOT_TEST_KEY", applied)
            self.assertEqual("from-the-environment", environment["SALESPILOT_TEST_KEY"])
        finally:
            os.environ.pop("SALESPILOT_TEST_KEY", None)

    def test_comments_blanks_and_malformed_lines_are_skipped(self):
        applied, _ = self._load(
            "# a comment\n"
            "\n"
            "   \n"
            "NOT_AN_ASSIGNMENT\n"
            "SALESPILOT_TEST_A=1\n"
        )
        self.assertEqual(["SALESPILOT_TEST_A"], applied)

    def test_one_layer_of_matching_quotes_is_stripped(self):
        _, environment = self._load(
            'SALESPILOT_TEST_Q="a value with spaces"\n'
            "SALESPILOT_TEST_S='single'\n"
        )
        self.assertEqual("a value with spaces", environment["SALESPILOT_TEST_Q"])
        self.assertEqual("single", environment["SALESPILOT_TEST_S"])

    def test_a_missing_file_is_not_an_error(self):
        self.assertEqual([], config.load_env_file(Path("no-such-file.env")))


class TestRedaction(unittest.TestCase):
    """A secret must be describable without being disclosed."""

    KEY = "sk-proj-0123456789abcdefghijklmnop"

    def test_the_key_never_appears_in_its_own_description(self):
        described = config.redact(self.KEY)
        self.assertNotIn(self.KEY, described)
        # Nor any run of it long enough to be worth having.
        for start in range(0, len(self.KEY) - 8):
            self.assertNotIn(self.KEY[start:start + 9], described)

    def test_absent_and_present_are_distinguishable(self):
        self.assertEqual("absent", config.redact(None))
        self.assertEqual("absent", config.redact(""))
        self.assertIn("set", config.redact(self.KEY))

    def test_no_key_characters_are_shown(self):
        """Presence and length are useful; a credential suffix is not."""
        self.assertNotIn("mnop", config.redact(self.KEY))
        self.assertEqual(f"set ({len(self.KEY)} chars)", config.redact(self.KEY))

    def test_a_short_secret_reveals_no_characters_at_all(self):
        self.assertEqual("set (6 chars)", config.redact("abc123"))

    def test_the_configuration_summary_never_carries_the_key(self):
        rendered = json.dumps(config.describe())
        if config.LLM_API_KEY:
            self.assertNotIn(config.LLM_API_KEY, rendered)


class TestResolve(unittest.TestCase):
    """Every refusal states a reason, because "offline" alone is unactionable."""

    def test_no_provider_selected_is_a_decision_with_a_reason(self):
        spec = resolve(provider="offline")
        self.assertTrue(spec.is_offline)
        self.assertEqual(offline.NO_PROVIDER_SELECTED, spec.reason)

    def test_every_spelling_of_off_is_accepted(self):
        for name in ("offline", "", "stub", "none", "OFFLINE", "  Offline  "):
            with self.subTest(name=name):
                self.assertTrue(resolve(provider=name).is_offline)

    def test_a_provider_with_no_key_runs_offline_rather_than_failing(self):
        """Failing every message would be the worse answer: a demo that dies because
        a key is missing is worse than one that runs visibly offline."""
        spec = resolve(provider="gateway", api_key="")
        self.assertTrue(spec.is_offline)
        self.assertEqual(offline.NO_API_KEY, spec.reason)

    def test_a_blank_model_name_runs_offline_rather_than_sending_an_unroutable_request(self):
        spec = resolve(provider="gateway", api_key="sk-x", model_name="   ")
        self.assertTrue(spec.is_offline)
        self.assertEqual(offline.NO_MODEL_NAME, spec.reason)

    def test_a_complete_configuration_resolves(self):
        spec = resolve(
            provider="gateway", api_key="sk-x", model_name="m-1",
            base_url="https://example.test/v1", timeout=12.0, max_tool_steps=4,
        )
        self.assertFalse(spec.is_offline)
        self.assertEqual("gateway", spec.provider)
        self.assertEqual("m-1", spec.model_name)
        self.assertEqual(12.0, spec.timeout)
        self.assertEqual(4, spec.max_tool_steps)
        self.assertEqual("configured", spec.reason)

    def test_describe_never_contains_the_key(self):
        spec = resolve(provider="gateway", api_key="sk-secret-value", model_name="m")
        self.assertNotIn("sk-secret-value", spec.describe())


class TestEndpoint(unittest.TestCase):
    """The most common misconfiguration here is a missing version path."""

    def test_the_completions_path_is_appended_to_the_configured_base(self):
        spec = resolve(provider="g", api_key="k", model_name="m",
                       base_url="https://example.test/v1")
        self.assertEqual("https://example.test/v1/chat/completions", spec.endpoint)

    def test_a_trailing_slash_does_not_double_up(self):
        spec = resolve(provider="g", api_key="k", model_name="m",
                       base_url="https://example.test/v1/")
        self.assertEqual("https://example.test/v1/chat/completions", spec.endpoint)

    def test_nothing_is_guessed_when_the_version_path_is_absent(self):
        """Deliberately not repaired. Inventing `/v1` would make a 404 mysterious;
        leaving it alone lets `probe` report the URL it actually called."""
        spec = resolve(provider="g", api_key="k", model_name="m",
                       base_url="https://example.test")
        self.assertEqual("https://example.test/chat/completions", spec.endpoint)

    def test_no_base_url_falls_back_to_the_openai_default(self):
        spec = resolve(provider="openai", api_key="k", model_name="m", base_url="")
        self.assertTrue(spec.endpoint.startswith("https://api.openai.com/v1"))


# ---- 2. The wire ---------------------------------------------------------


class TestProbeAgainstARealServer(unittest.TestCase):
    """Five outcomes that all look like "offline" from the outside."""

    def test_an_offline_spec_is_reported_without_a_request(self):
        result = probe(resolve(provider="offline"))
        self.assertFalse(result.reachable)
        self.assertIn("offline", result.summary)
        self.assertIsNone(result.status)

    def test_a_working_endpoint_is_reachable_and_timed(self):
        with _FakeEndpoint("ok") as endpoint:
            result = probe(endpoint.spec())
        self.assertTrue(result.reachable, result.detail)
        self.assertEqual(200, result.status)
        self.assertEqual("ok", result.model_reply)
        self.assertIsNotNone(result.latency_ms)

    def test_the_request_carries_the_bearer_token_and_the_model(self):
        with _FakeEndpoint("ok") as endpoint:
            probe(endpoint.spec())
            path, headers, body = endpoint.requests[0]
        self.assertEqual("/v1/chat/completions", path)
        self.assertEqual("Bearer sk-test-key", headers["Authorization"])
        self.assertEqual("test-model", body["model"])

    def test_a_rejected_credential_is_distinguished_from_an_unreachable_host(self):
        """The two diagnoses send an operator to different places: one is the network
        or the URL, the other is the credential or the account."""
        with _FakeEndpoint("unauthorized") as endpoint:
            rejected = probe(endpoint.spec())
        self.assertFalse(rejected.reachable)
        self.assertEqual(401, rejected.status)
        self.assertIn("rejected the credential", rejected.detail)

    def test_an_unknown_model_names_the_version_path_as_a_suspect(self):
        with _FakeEndpoint("not_found") as endpoint:
            result = probe(endpoint.spec())
        self.assertEqual(404, result.status)
        self.assertIn("/v1", result.detail)

    def test_a_two_hundred_that_is_not_a_completion_is_not_reachable(self):
        """Something is answering, but it is not the API. A proxy login page does
        exactly this, and calling it "reachable" would send somebody hunting for a
        model problem that does not exist."""
        with _FakeEndpoint("not_a_completion") as endpoint:
            result = probe(endpoint.spec())
        self.assertFalse(result.reachable)
        self.assertEqual(200, result.status)
        self.assertIn("not a chat completion", result.detail)

    def test_a_closed_port_is_reported_as_unreachable_rather_than_raising(self):
        endpoint = _FakeEndpoint("ok")
        base = endpoint.base_url
        endpoint.server.server_close()  # nothing is listening now
        result = probe(resolve(provider="g", api_key="k", model_name="m",
                               base_url=base, timeout=3.0))
        self.assertFalse(result.reachable)
        self.assertIn(base, result.detail)

    def test_the_key_never_reaches_the_summary_of_a_success(self):
        with _FakeEndpoint("ok") as endpoint:
            result = probe(endpoint.spec())
        self.assertNotIn("sk-test-key", result.summary)


class TestModelFactory(unittest.TestCase):
    """Constructing a model is the one thing `providers` is not allowed to do."""

    def test_an_offline_spec_passes_through_with_its_reason(self):
        from backend.agent.model_factory import build

        built = build(resolve(provider="offline"))
        self.assertTrue(built.is_offline)
        self.assertIn("offline", built.describe())
        self.assertEqual(offline.NO_PROVIDER_SELECTED, built.reason)

    def test_a_configured_spec_produces_a_callable_model(self):
        from backend.agent.model_factory import build

        built = build(resolve(provider="gateway", api_key="sk-x", model_name="m-1",
                              base_url="https://example.test/v1"))
        self.assertFalse(built.is_offline, built.reason)
        self.assertIsNotNone(built.model)

    def test_a_known_gateway_model_gets_server_side_costing(self):
        from backend.agent.costed_model import CostedGatewayModel
        from backend.agent.model_factory import build

        built = build(resolve(
            provider="gateway", api_key="sk-x",
            model_name="global.anthropic.claude-sonnet-4-5-20250929-v1:0",
            base_url="https://example.test/v1",
        ))
        self.assertIsInstance(built.model, CostedGatewayModel)

    def test_construction_failure_degrades_instead_of_refusing_to_start(self):
        from backend.agent.model_factory import build

        built = build(resolve(provider="gateway", api_key="sk-x", model_name="m",
                              base_url="not a url at all"))
        # Either it constructs (the client is lazy about URLs) or it degrades with a
        # reason. What it must never do is raise out of `build`.
        if built.is_offline:
            self.assertTrue(built.reason)

    def test_the_built_description_never_contains_the_key(self):
        from backend.agent.model_factory import build

        built = build(resolve(provider="gateway", api_key="sk-secret-abc",
                              model_name="m", base_url="https://example.test/v1"))
        self.assertNotIn("sk-secret-abc", built.describe())


# ---- 3. Cost accounting --------------------------------------------------


def _service(model):
    from backend.agent.runtime import AgentRuntime
    from backend.knowledge import loader
    from backend.services.conversation import ConversationService
    from backend.storage.memory import InMemoryRepository

    runtime = AgentRuntime(kb=loader.load(), model=model, max_tool_calls=7)
    return ConversationService(
        InMemoryRepository(), model=model, runtime=runtime, trace=False
    )


def _test_model(**kwargs):
    from pydantic_ai.models.test import TestModel

    return TestModel(**kwargs)


class TestCostAccountingOnTheModelPath(unittest.TestCase):
    """The regression tests for the defect described at the top of this file.

    All of them run on `TestModel`: no network, no key, no fake server. That is the
    point - the coverage gap needed no infrastructure to close, only a fixture on
    which zero was not the correct answer.
    """

    def _run(self, text: str = "How much is the Plus plan?") -> dict:
        service = _service(_test_model(call_tools="all"))
        result = service.handle_customer_message(
            customer_id="C-1", customer_name="Test", text=text
        )
        return result.to_dict()["agent_run"]

    def test_both_model_calls_are_recorded(self):
        """Two segments, two calls: the observing one and the composing one."""
        totals = self._run()["totals"]
        self.assertEqual(2, totals["llm_call_count"])

    def test_the_recorded_calls_name_the_segment_they_served(self):
        purposes = [call["purpose"] for call in self._run()["llm_calls"]]
        self.assertEqual(["extraction", "response_generation"], purposes)

    def test_tokens_are_counted_rather_than_reported_as_zero(self):
        run = self._run()
        self.assertGreater(run["totals"]["total_tokens"], 0)
        for call in run["llm_calls"]:
            with self.subTest(purpose=call["purpose"]):
                self.assertGreater(call["prompt_tokens"], 0)
                self.assertEqual(
                    call["prompt_tokens"] + call["completion_tokens"],
                    call["total_tokens"],
                )

    def test_the_total_is_the_sum_of_the_calls(self):
        run = self._run()
        self.assertEqual(
            sum(call["total_tokens"] for call in run["llm_calls"]),
            run["totals"]["total_tokens"],
        )

    def test_an_unpriced_model_reports_unknown_rather_than_zero(self):
        """The damaging shape of this defect was not a wrong number, it was
        `{"amount": 0.0, "pricing_known": true}` - a claim that the spend was measured
        and was nothing. `TestModel` reports its name as `test`, which is not in the
        price table, so the honest answer is that the cost is unknown."""
        cost = self._run()["totals"]["cost"]
        self.assertFalse(cost["pricing_known"])
        self.assertEqual(0.0, cost["amount"])

    def test_the_offline_path_records_no_calls_and_that_is_correct(self):
        """The assertion that used to be the only one, kept because it is still true.
        Zero here means no model ran, not that a model ran for free."""
        run = _service(None).handle_customer_message(
            customer_id="C-1", customer_name="Test", text="How much is Plus?"
        ).to_dict()["agent_run"]
        self.assertEqual(0, run["totals"]["llm_call_count"])
        self.assertEqual(0, run["totals"]["total_tokens"])
        self.assertEqual("degraded", run["status"])

    def test_model_selected_tool_calls_are_recorded_too(self):
        run = self._run()
        self.assertGreater(run["totals"]["tool_call_count"], 0)
        for call in run["tool_calls"]:
            with self.subTest(name=call["name"]):
                self.assertTrue(call["name"])

    def test_retrieval_is_not_counted_as_a_model_chosen_tool_call(self):
        """`interface-v1.md` §1.1 rule 2: retrieval is a kernel step. Inflating the
        tool-call count with it would overstate what the model actually did."""
        run = self._run()
        self.assertNotIn(
            "knowledge_retrieval", [call["name"] for call in run["tool_calls"]]
        )


class TestUsageExtraction(unittest.TestCase):
    """Reading usage must never be the thing that costs the customer a reply."""

    def test_a_result_without_usage_yields_none_rather_than_raising(self):
        from backend.agent.usage import from_result

        class Bare:
            pass

        self.assertIsNone(
            from_result(Bare(), purpose="extraction", duration_ms=1)
        )

    def test_an_unreadable_message_list_does_not_propagate(self):
        from backend.agent.usage import from_result

        class Usage:
            input_tokens = 10
            output_tokens = 2
            requests = 1

        class Result:
            usage = Usage()

            def all_messages(self):
                raise RuntimeError("the framework changed shape")

        usage = from_result(
            Result(), purpose="extraction", duration_ms=5, configured_model="m-1"
        )
        self.assertIsNotNone(usage)
        self.assertEqual("m-1", usage.model)
        self.assertEqual(12, usage.total_tokens)

    def test_the_provider_reported_model_wins_over_the_configured_one(self):
        """A gateway may serve something other than what was asked for, and the
        *served* model is the one that determines the price."""
        from backend.agent.usage import from_result

        class Usage:
            input_tokens = 1
            output_tokens = 1
            requests = 1

        class Response:
            model_name = "gpt-4o-mini"

        class Result:
            usage = Usage()

            def all_messages(self):
                return [Response()]

        usage = from_result(
            Result(), purpose="extraction", duration_ms=1, configured_model="asked-for"
        )
        self.assertEqual("gpt-4o-mini", usage.model)

    def test_unreadable_usage_makes_the_reply_degrade_rather_than_go_unremarked(self):
        """An unaccounted call must be visible. The alternative is a run that reports
        a confident zero for a call that really happened."""
        from backend.agent.reply import ReplyRequest
        from backend.agent.reply.model_based import ModelComposer
        from backend.domain.decision import NextBestAction
        from backend.domain.enums import Priority, ReplyMode

        class NoUsageResult:
            output = "Here is a reply."
            usage = None

            def all_messages(self):
                return []

        class StubAgent:
            def __init__(self, *args, **kwargs):
                pass

            def run_sync(self, *args, **kwargs):
                return NoUsageResult()

        composer = ModelComposer(object())
        request = ReplyRequest(
            facts=["a fact"],
            action=NextBestAction(
                action="a", reason="b", priority=Priority.LOW,
                reply_mode=ReplyMode.NURTURE,
            ),
        )
        import backend.agent.reply.model_based as module

        original = module.Agent
        module.Agent = StubAgent
        try:
            outcome = composer.compose(request)
        finally:
            module.Agent = original

        self.assertTrue(outcome.degraded)
        self.assertIn("cost accounting", outcome.degradation_reason or "")


class TestModelListing(unittest.TestCase):
    """`GET /models` turns a guessed model name into a read one."""

    def test_a_model_list_is_read_and_sorted(self):
        class _Handler(_FakeHandler):
            def do_GET(self):
                body = json.dumps(
                    {"data": [{"id": "b-model"}, {"id": "a-model"}]}
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        server = HTTPServer(("127.0.0.1", 0), _Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            spec = resolve(
                provider="g", api_key="k", model_name="m",
                base_url=f"http://127.0.0.1:{server.server_port}/v1",
            )
            names, detail = probe_models(spec, timeout=5.0)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
        self.assertEqual(["a-model", "b-model"], names)
        self.assertIn("2 models", detail)

    def test_an_endpoint_without_the_route_returns_no_names_and_no_exception(self):
        with _FakeEndpoint("ok") as endpoint:
            # The fake only answers POST, so GET /models is a 501 from the base class.
            names, detail = probe_models(endpoint.spec(), timeout=5.0)
        self.assertEqual([], names)
        self.assertTrue(detail)

    def test_a_closed_port_returns_no_names_and_no_exception(self):
        endpoint = _FakeEndpoint("ok")
        base = endpoint.base_url
        endpoint.server.server_close()
        names, detail = probe_models(
            resolve(provider="g", api_key="k", model_name="m",
                    base_url=base, timeout=3.0)
        )
        self.assertEqual([], names)
        self.assertTrue(detail)


if __name__ == "__main__":
    unittest.main()
