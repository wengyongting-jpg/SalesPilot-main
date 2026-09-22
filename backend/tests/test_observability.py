# -*- coding: utf-8 -*-
"""P4: agent run records, cost accounting, and the terminal renderer.

Wire shape: `docs/api/interface-v1.md` §5.3, field for field.

The requirement this phase exists to meet, in the owner's words: when the program is
wrong there is an error, but when the *model* is wrong there is no warning at all, and
finding the problem needs enough information to be there in the first place. So the
central assertion here is that **three failure classes stay distinguishable**:

    program error       an exception — surfaced, with a stack trace
    model unavailable   no key, a timeout, a rate limit — degraded
    model wrong         an invalid enum, unparsable output — degraded, and the
                        offending value is named

The frozen build could express the first. The second was visible only as a response
field nobody watched. The third was invisible.
"""
from __future__ import annotations

import unittest
from datetime import datetime

from backend.observability.violations import ModelViolation

NOW = datetime(2026, 9, 22, 12, 0, 0)


class FakeClock:
    """A monotonic clock that only moves when told to, so durations are exact."""

    def __init__(self) -> None:
        self.seconds = 0.0

    def __call__(self) -> float:
        return self.seconds

    def advance(self, ms: float) -> None:
        self.seconds += ms / 1000.0


def recorder(**kwargs):
    from backend.observability.recorder import RunRecorder

    clock = kwargs.pop("clock", None) or FakeClock()
    defaults = dict(
        opportunity_id="C-1024",
        client_message_id="c-8f2a1b40",
        customer_message_count=3,
        clock=clock,
        now=lambda: NOW,
    )
    defaults.update(kwargs)
    return RunRecorder(**defaults), clock


class TestRunRecordShape(unittest.TestCase):
    """The admin console reads this payload, so its shape is a contract."""

    def test_the_top_level_keys_match_the_interface(self):
        rec, _ = recorder()
        payload = rec.finish().to_dict()
        self.assertEqual(
            {
                "run_id", "opportunity_id", "client_message_id", "trigger",
                "customer_message_count", "started_at", "finished_at",
                "duration_ms", "status", "steps", "llm_calls", "tool_calls",
                "violations", "totals",
            },
            set(payload),
        )

    def test_a_run_id_is_generated_and_prefixed(self):
        rec, _ = recorder()
        self.assertTrue(rec.finish().to_dict()["run_id"].startswith("ar-"))

    def test_the_default_trigger_is_a_customer_message(self):
        rec, _ = recorder()
        self.assertEqual("customer_message", rec.finish().to_dict()["trigger"])

    def test_a_step_reports_index_name_kind_duration_and_status(self):
        from backend.observability.run import StepKind

        rec, clock = recorder()
        with rec.step("extraction", StepKind.LLM):
            clock.advance(820)
        payload = rec.finish().to_dict()
        step = payload["steps"][0]
        self.assertEqual(
            {"index", "name", "kind", "duration_ms", "status", "detail"}, set(step)
        )
        self.assertEqual(0, step["index"])
        self.assertEqual("extraction", step["name"])
        self.assertEqual("llm", step["kind"])
        self.assertEqual(820, step["duration_ms"])
        self.assertEqual("ok", step["status"])

    def test_steps_are_indexed_in_order(self):
        from backend.observability.run import StepKind

        rec, _ = recorder()
        for name in ("extraction", "state_transition", "scoring"):
            with rec.step(name, StepKind.RULE):
                pass
        payload = rec.finish().to_dict()
        self.assertEqual([0, 1, 2], [s["index"] for s in payload["steps"]])


class TestTotals(unittest.TestCase):
    def test_totals_equal_the_sum_of_the_parts(self):
        """A dashboard whose total disagrees with its rows teaches people to
        distrust both."""
        from backend.observability.run import StepKind

        rec, clock = recorder()
        with rec.step("extraction", StepKind.LLM):
            clock.advance(800)
        rec.record_llm_call(
            purpose="extraction", model="gpt-4o-mini", duration_ms=800,
            prompt_tokens=412, completion_tokens=88,
            input_text="x" * 2180, output_text="y" * 142,
        )
        with rec.step("response_generation", StepKind.LLM):
            clock.advance(400)
        rec.record_llm_call(
            purpose="response_generation", model="gpt-4o-mini", duration_ms=400,
            prompt_tokens=298, completion_tokens=64,
            input_text="x" * 900, output_text="y" * 200,
        )
        payload = rec.finish().to_dict()
        totals = payload["totals"]

        self.assertEqual(len(payload["steps"]), totals["agent_step_count"])
        self.assertEqual(2, totals["llm_call_count"])
        self.assertEqual(
            sum(call["total_tokens"] for call in payload["llm_calls"]),
            totals["total_tokens"],
        )
        self.assertAlmostEqual(
            sum(call["cost"]["amount"] for call in payload["llm_calls"]),
            totals["cost"]["amount"],
            places=10,
        )

    def test_duration_covers_the_whole_run(self):
        from backend.observability.run import StepKind

        rec, clock = recorder()
        clock.advance(40)
        with rec.step("extraction", StepKind.LLM):
            clock.advance(800)
        clock.advance(10)
        self.assertEqual(850, rec.finish().to_dict()["duration_ms"])


class TestToolCallCounting(unittest.TestCase):
    """`interface-v1.md` §1.1 rule 2, which exists because this is tempting to fake."""

    def test_only_model_selected_calls_count_as_tool_calls(self):
        from backend.agent.tools import ToolCall
        from backend.observability.run import StepKind

        rec, _ = recorder()
        with rec.step("knowledge_retrieval", StepKind.RETRIEVAL):
            pass
        rec.record_tool_calls([
            ToolCall(name="lookup_product_fact", arguments={"product": "plus"},
                     result_chars=120),
        ])
        payload = rec.finish().to_dict()

        self.assertEqual(1, payload["totals"]["tool_call_count"])
        self.assertEqual(["lookup_product_fact"],
                         [call["name"] for call in payload["tool_calls"]])

    def test_retrieval_is_reported_as_retrieval_and_counts_as_no_tool_call(self):
        """Fixed pipeline retrieval is not something the model chose. Counting it to
        make a dashboard look busier would manufacture the defect the rule forbids."""
        from backend.observability.run import StepKind

        rec, _ = recorder()
        with rec.step("knowledge_retrieval", StepKind.RETRIEVAL):
            pass
        payload = rec.finish().to_dict()
        self.assertEqual("retrieval", payload["steps"][0]["kind"])
        self.assertEqual(0, payload["totals"]["tool_call_count"])
        self.assertEqual([], payload["tool_calls"])


class TestThreeFailureClasses(unittest.TestCase):
    """The reason this phase exists."""

    def test_a_clean_run_is_ok(self):
        from backend.observability.run import StepKind

        rec, _ = recorder()
        with rec.step("scoring", StepKind.RULE):
            pass
        self.assertEqual("ok", rec.finish().to_dict()["status"])

    def test_model_unavailable_is_degraded_with_a_stated_reason(self):
        from backend.observability.run import StepKind

        rec, _ = recorder()
        with rec.step("extraction", StepKind.LLM) as step:
            step.degraded("no model configured; used the rule-based peer")
        payload = rec.finish().to_dict()
        self.assertEqual("degraded", payload["status"])
        self.assertEqual("degraded", payload["steps"][0]["status"])
        self.assertIn("rule-based", payload["steps"][0]["detail"])

    def test_model_wrong_is_degraded_and_names_the_offending_value(self):
        """The class that was entirely invisible before."""
        from backend.observability.run import StepKind

        rec, _ = recorder()
        with rec.step("extraction", StepKind.LLM) as step:
            step.violation(
                ModelViolation(
                    field="intent", value="medical_question",
                    allowed=["generic", "price", "underwriting"],
                )
            )
        payload = rec.finish().to_dict()
        self.assertEqual("degraded", payload["status"])
        self.assertEqual("medical_question", payload["violations"][0]["value"])
        self.assertEqual("intent", payload["violations"][0]["field"])
        self.assertIn("medical_question", payload["steps"][0]["detail"])

    def test_a_program_error_is_an_error_not_a_degradation(self):
        """Conflating a bug with a provider hiccup sends whoever is debugging to the
        wrong place, which is the specific cost this separation avoids."""
        from backend.observability.run import StepKind

        rec, _ = recorder()
        with self.assertRaises(ZeroDivisionError):
            with rec.step("scoring", StepKind.RULE):
                1 / 0
        payload = rec.finish().to_dict()
        self.assertEqual("error", payload["status"])
        self.assertEqual("error", payload["steps"][0]["status"])
        self.assertIn("ZeroDivisionError", payload["steps"][0]["detail"])

    def test_an_error_outranks_a_degradation(self):
        from backend.observability.run import StepKind

        rec, _ = recorder()
        with rec.step("extraction", StepKind.LLM) as step:
            step.degraded("fell back to rules")
        with self.assertRaises(ValueError):
            with rec.step("scoring", StepKind.RULE):
                raise ValueError("boom")
        self.assertEqual("error", rec.finish().to_dict()["status"])


class TestCostAccounting(unittest.TestCase):
    """Computed server-side. A frontend holding a price table is business logic in
    the wrong layer."""

    def test_cost_follows_the_token_price_table(self):
        from backend.observability import pricing

        money = pricing.cost_for("gpt-4o-mini", prompt_tokens=1_000_000,
                                 completion_tokens=0)
        self.assertAlmostEqual(0.15, money.amount, places=6)
        self.assertEqual("USD", money.currency)
        self.assertTrue(money.pricing_known)

    def test_output_tokens_are_priced_higher_than_input(self):
        from backend.observability import pricing

        cheap = pricing.cost_for("gpt-4o-mini", prompt_tokens=1000, completion_tokens=0)
        dear = pricing.cost_for("gpt-4o-mini", prompt_tokens=0, completion_tokens=1000)
        self.assertGreater(dear.amount, cheap.amount)

    def test_gateway_claude_sonnet_45_has_known_pricing(self):
        from backend.observability import pricing

        money = pricing.cost_for(
            "global.anthropic.claude-sonnet-4-5-20250929-v1:0",
            prompt_tokens=1_000_000,
            completion_tokens=1_000_000,
        )
        self.assertTrue(money.pricing_known)
        self.assertAlmostEqual(18.0, money.amount, places=6)

    def test_an_unknown_model_is_reported_as_unknown_not_as_free(self):
        """Zero cost and unknown cost are different claims. Showing an unpriced model
        as $0.00 invites somebody to budget against it."""
        from backend.observability import pricing

        money = pricing.cost_for("some-new-model", prompt_tokens=5000,
                                 completion_tokens=500)
        self.assertFalse(money.pricing_known)
        self.assertEqual(0.0, money.amount)

    def test_the_serialised_cost_carries_the_unknown_flag(self):
        rec, _ = recorder()
        rec.record_llm_call(
            purpose="extraction", model="some-new-model", duration_ms=100,
            prompt_tokens=10, completion_tokens=10,
            input_text="a", output_text="b",
        )
        cost = rec.finish().to_dict()["llm_calls"][0]["cost"]
        self.assertEqual({"amount", "currency", "pricing_known"}, set(cost))
        self.assertFalse(cost["pricing_known"])


class TestContentGating(unittest.TestCase):
    """`interface-v1.md` §5.3 item 4: prompts may contain the customer's own words."""

    def _call(self, capture: bool):
        rec, _ = recorder(capture_content=capture)
        rec.record_llm_call(
            purpose="extraction", model="gpt-4o-mini", duration_ms=10,
            prompt_tokens=10, completion_tokens=10,
            input_text="the customer said something private",
            output_text="a reply",
        )
        return rec.finish().to_dict()["llm_calls"][0]

    def test_lengths_are_always_reported(self):
        for capture in (True, False):
            with self.subTest(capture=capture):
                call = self._call(capture)
                self.assertEqual(35, call["input"]["chars"])
                self.assertEqual(7, call["output"]["chars"])

    def test_content_is_present_when_capture_is_on(self):
        call = self._call(True)
        self.assertIn("private", call["input"]["content"])

    def test_content_is_withheld_when_capture_is_off(self):
        call = self._call(False)
        self.assertIsNone(call["input"]["content"])
        self.assertIsNone(call["output"]["content"])

    def test_captured_content_is_truncated_rather_than_unbounded(self):
        rec, _ = recorder(capture_content=True, content_max_chars=50)
        rec.record_llm_call(
            purpose="extraction", model="gpt-4o-mini", duration_ms=10,
            prompt_tokens=10, completion_tokens=10,
            input_text="x" * 5000, output_text="y",
        )
        call = rec.finish().to_dict()["llm_calls"][0]
        self.assertEqual(5000, call["input"]["chars"], "the true length must survive")
        self.assertLessEqual(len(call["input"]["content"]), 51)


class TestConsoleRenderer(unittest.TestCase):
    """What a developer actually sees in the terminal."""

    def _run(self, *, degraded=False, violation=False, error=False):
        from backend.observability.run import StepKind

        rec, clock = recorder()
        with rec.step("extraction", StepKind.LLM) as step:
            clock.advance(820)
            if degraded:
                step.degraded("no model configured; used the rule-based peer")
            if violation:
                step.violation(
                    ModelViolation(field="intent", value="medical_question",
                                   allowed=["generic", "underwriting"])
                )
        rec.record_llm_call(
            purpose="extraction", model="gpt-4o-mini", duration_ms=820,
            prompt_tokens=412, completion_tokens=88,
            input_text="x" * 100, output_text="y" * 20,
        )
        if error:
            try:
                with rec.step("scoring", StepKind.RULE):
                    raise RuntimeError("boom")
            except RuntimeError:
                pass
        else:
            with rec.step("scoring", StepKind.RULE):
                clock.advance(1)
        return rec.finish()

    def test_a_normal_run_renders_one_block_with_steps_and_totals(self):
        from backend.observability import console

        text = console.render(self._run())
        self.assertIn("ar-", text)
        self.assertIn("C-1024", text)
        self.assertIn("extraction", text)
        self.assertIn("gpt-4o-mini", text)
        self.assertIn("820ms", text)
        self.assertIn("500", text)          # token total
        self.assertIn("scoring", text)
        self.assertIn("ok", text)

    def test_a_degradation_renders_as_a_warning_with_its_reason(self):
        from backend.observability import console

        text = console.render(self._run(degraded=True))
        self.assertIn("DEGRADED", text.upper())
        self.assertIn("rule-based", text)

    def test_a_violation_names_the_offending_value(self):
        from backend.observability import console

        text = console.render(self._run(violation=True))
        self.assertIn("medical_question", text)

    def test_a_detail_line_is_never_clipped(self):
        """The diagnostic payload is the whole point of printing it. The first
        renderer clipped every line to the column width, which cut a violation off
        just before the permitted values — the one part a reader needs."""
        from backend.observability import console

        text = console.render(self._run(violation=True), width=60)
        self.assertIn("allowed:", text)
        self.assertIn("underwriting", text)

    def test_aligned_lines_are_still_clipped_so_columns_stay_readable(self):
        from backend.observability import console

        text = console.render(self._run(), width=50)
        step_lines = [
            line for line in text.splitlines() if " llm " in line or " rule " in line
        ]
        self.assertTrue(step_lines)
        for line in step_lines:
            self.assertLessEqual(len(line), 50)

    def test_an_error_is_rendered_distinctly_from_a_degradation(self):
        from backend.observability import console

        error_text = console.render(self._run(error=True))
        degraded_text = console.render(self._run(degraded=True))
        self.assertIn("ERROR", error_text.upper())
        self.assertNotIn("ERROR", degraded_text.upper())

    def test_the_default_rendering_is_ascii_only(self):
        """A Windows console at its default code page mangles box-drawing glyphs, and
        a report about something being broken should not itself look broken."""
        from backend.observability import console

        for kwargs in ({"degraded": True}, {"violation": True}, {"error": True}, {}):
            with self.subTest(**kwargs):
                text = console.render(self._run(**kwargs))
                self.assertTrue(text.isascii(), f"non-ascii in output: {text!r}")

    def test_a_long_allowed_list_elides_in_ascii(self):
        """The truncating branch is the common one: the enums this reports on have
        eleven and fourteen members, so the elision marker is almost always printed.
        An earlier version used a horizontal ellipsis there and broke the guarantee
        above for every realistic violation."""
        from backend.observability import console
        from backend.observability.run import StepKind

        rec, _ = recorder()
        with rec.step("extraction", StepKind.LLM) as step:
            step.violation(
                ModelViolation(
                    field="intent",
                    value="medical_question",
                    allowed=[f"value_{index}" for index in range(14)],
                )
            )
        text = console.render(rec.finish())
        self.assertTrue(text.isascii(), f"non-ascii in output: {text!r}")
        self.assertIn("...", text)

    def test_rendering_is_deterministic_for_a_fixed_clock(self):
        from backend.observability import console

        first = console.render(self._run())
        second = console.render(self._run())
        # Only the generated run id differs.
        self.assertEqual(
            _without_run_id(first), _without_run_id(second)
        )


def _without_run_id(text: str) -> str:
    import re

    return re.sub(r"ar-[0-9a-f]+", "ar-XXXX", text)


class TestLayering(unittest.TestCase):
    def test_the_deterministic_core_is_not_instrumented(self):
        """Business rules stay readable and unit-testable with no recorder in scope.
        Enforced globally by `test_architecture`; restated here for the reason."""
        import ast
        import pathlib

        import backend.kernel as kernel_package

        offenders = []
        for path in pathlib.Path(kernel_package.__file__).parent.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""] + [a.name for a in node.names]
                if any("observability" in name for name in names):
                    offenders.append(f"{path.name}:{node.lineno}")
        self.assertEqual([], offenders)


if __name__ == "__main__":
    unittest.main()


class TestExpectedDegradationIsNotWarnedAbout(unittest.TestCase):
    """Alarm fatigue is the same failure as no alarm, arrived at from the other side.

    Offline is the documented default and every run in it degrades. Reporting each one
    at WARNING costs twice: the default mode reads as broken, and a real warning — a
    provider timing out, a model returning a value the domain rejects — arrives inside
    a stream of identical expected ones and is missed.

    So the level splits while the *record* does not: the run still reports
    `status: "degraded"` and the reason is still on the step. Only the loudness moves.
    """

    def _run(self, build):
        rec, _ = recorder()
        build(rec)
        return rec.finish()

    def test_a_degradation_that_is_the_configured_mode_is_reported_at_info(self):
        import logging

        from backend.observability.logging import _level_for
        from backend.observability.run import StepKind

        def build(rec):
            with rec.step("extraction", StepKind.LLM) as step:
                step.degraded("no model configured", by_design=True)

        run = self._run(build)
        self.assertTrue(run.degraded_by_design)
        self.assertEqual(logging.INFO, _level_for(run))

    def test_an_unexpected_degradation_is_still_a_warning(self):
        import logging

        from backend.observability.logging import _level_for
        from backend.observability.run import StepKind

        def build(rec):
            with rec.step("extraction", StepKind.LLM) as step:
                step.degraded("the provider timed out")

        run = self._run(build)
        self.assertFalse(run.degraded_by_design)
        self.assertEqual(logging.WARNING, _level_for(run))

    def test_expected_is_not_the_default(self):
        """A new degradation has to claim to be expected rather than inheriting it by
        omission, or the next one added quietly stops being warned about."""
        from backend.observability.run import RunStatus, StepKind

        def build(rec):
            with rec.step("extraction", StepKind.LLM) as step:
                step.degraded("something went wrong")

        run = self._run(build)
        self.assertIs(RunStatus.DEGRADED, run.steps[0].status)
        self.assertFalse(run.steps[0].by_design)

    def test_one_real_fault_alongside_an_expected_one_earns_a_warning(self):
        import logging

        from backend.observability.logging import _level_for
        from backend.observability.run import StepKind

        def build(rec):
            with rec.step("extraction", StepKind.LLM) as step:
                step.degraded("no model configured", by_design=True)
            with rec.step("response_generation", StepKind.LLM) as step:
                step.degraded("the provider returned an empty reply")

        run = self._run(build)
        self.assertFalse(
            run.degraded_by_design,
            "all, not any: one genuine fault makes the whole run worth a warning",
        )
        self.assertEqual(logging.WARNING, _level_for(run))

    def test_a_second_reason_on_the_same_step_can_withdraw_expectedness(self):
        from backend.observability.run import StepKind

        def build(rec):
            with rec.step("extraction", StepKind.LLM) as step:
                step.degraded("no model configured", by_design=True)
                step.degraded("and the knowledge base failed to load")

        run = self._run(build)
        self.assertFalse(run.steps[0].by_design)

    def test_a_violation_is_never_expected(self):
        """The model and the domain have disagreed — the defect class the rebuild
        exists to surface. It must not inherit an offline step's exemption."""
        import logging

        from backend.observability.logging import _level_for
        from backend.observability.run import StepKind

        def build(rec):
            with rec.step("extraction", StepKind.LLM) as step:
                step.degraded("no model configured", by_design=True)
                step.violation(
                    ModelViolation(
                        field="intent", value="medical_question",
                        allowed=["generic", "underwriting"],
                    )
                )

        run = self._run(build)
        self.assertFalse(run.steps[0].by_design)
        self.assertEqual(logging.WARNING, _level_for(run))

    def test_an_error_is_still_an_error(self):
        import logging

        from backend.observability.logging import _level_for
        from backend.observability.run import RunStatus, StepKind

        rec, _ = recorder()
        with self.assertRaises(ValueError):
            with rec.step("extraction", StepKind.LLM):
                raise ValueError("boom")
        run = rec.finish()
        self.assertIs(RunStatus.ERROR, run.status)
        self.assertEqual(logging.ERROR, _level_for(run))

    def test_a_clean_run_is_info_and_is_not_claimed_as_a_degradation(self):
        import logging

        from backend.observability.logging import _level_for
        from backend.observability.run import StepKind

        def build(rec):
            with rec.step("scoring", StepKind.RULE):
                pass

        run = self._run(build)
        self.assertFalse(
            run.degraded_by_design,
            "a run with no degradation at all has none by design either",
        )
        self.assertEqual(logging.INFO, _level_for(run))

    def test_the_classification_never_reaches_the_wire(self):
        """`interface-v1.md` is frozen, so no field may be added to the payload. This
        exists to choose a log level and for nothing else."""
        import json

        from backend.observability.run import StepKind

        def build(rec):
            with rec.step("extraction", StepKind.LLM) as step:
                step.degraded("no model configured", by_design=True)

        payload = self._run(build).to_dict()
        self.assertNotIn("by_design", json.dumps(payload))
        self.assertEqual(
            {"index", "name", "kind", "duration_ms", "status", "detail"},
            set(payload["steps"][0]),
        )

    def test_the_reason_is_still_recorded_and_the_status_still_says_degraded(self):
        """Nothing is hidden by the quieter level."""
        from backend.observability.run import StepKind

        def build(rec):
            with rec.step("extraction", StepKind.LLM) as step:
                step.degraded("no model configured", by_design=True)

        payload = self._run(build).to_dict()
        self.assertEqual("degraded", payload["status"])
        self.assertEqual("degraded", payload["steps"][0]["status"])
        self.assertEqual("no model configured", payload["steps"][0]["detail"])


class TestTheOfflinePipelineIsQuietButHonest(unittest.TestCase):
    """The end-to-end version, through the real services layer."""

    def _run_one(self, model):
        from backend.services.conversation import ConversationService
        from backend.storage.memory import InMemoryRepository

        service = ConversationService(
            InMemoryRepository(), model=model, trace=False
        )
        return service.handle_customer_message(
            customer_id="C-1", customer_name="M", text="How much is the Plus plan?"
        ).to_dict()["agent_run"]

    def test_an_offline_run_degrades_at_info_level(self):
        import logging

        from backend.observability.logging import _level_for
        from backend.observability.recorder import RunRecorder  # noqa: F401
        from backend.observability.run import AgentRun, RunStatus, RunStep, StepKind

        payload = self._run_one(None)
        self.assertEqual("degraded", payload["status"])

        # Rebuild enough of the run to ask the level question, since `to_dict` does not
        # carry the classification by design.
        rebuilt = AgentRun(opportunity_id=payload["opportunity_id"])
        rebuilt.status = RunStatus.DEGRADED
        for index, step in enumerate(payload["steps"]):
            rebuilt.steps.append(
                RunStep(
                    index=index, name=step["name"], kind=StepKind(step["kind"]),
                    duration_ms=step["duration_ms"],
                    status=RunStatus(step["status"]),
                    by_design=step["status"] == "degraded",
                )
            )
        self.assertEqual(logging.INFO, _level_for(rebuilt))

    def test_both_offline_steps_name_the_reason_they_degraded(self):
        payload = self._run_one(None)
        degraded = {
            step["name"]: step["detail"]
            for step in payload["steps"] if step["status"] == "degraded"
        }
        self.assertEqual({"extraction", "response_generation"}, set(degraded))
        for name, detail in degraded.items():
            with self.subTest(step=name):
                self.assertTrue(detail, "a quieter level must not mean a silent one")
                self.assertIn("model", detail)
