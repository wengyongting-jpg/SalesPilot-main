# -*- coding: utf-8 -*-
"""P4: agent run records, cost accounting and terminal rendering.

Acceptance criteria from `docs/backend-plan.md` §9, restated as assertions:

    1. A normal run prints one block with per-step kind, duration, status,
       model, tokens and cost, and totals that equal the sum of the parts.
    3. `tool_call_count` reflects only model-selected calls. Retrieval
       reports `kind: "retrieval"` and does not increment it.
    4. `kernel/` and `domain/` contain no import of `observability/`
       (enforced by `test_architecture.py`).

Plus `backend-contract.md` item 8: cost absent (not 0) when unpriced; `chars`
always present and `content` absent when the content flag is off.

Acceptance check 2 (three failure classes) lives with the agent peers in
`test_agent_extraction.py`, where the failures are actually produced.
"""
from __future__ import annotations

import itertools
import unittest
from decimal import Decimal

from backend.observability import RunRecorder, render
from backend.observability.pricing import cost_for


def _ticking_clock(step_seconds: float = 0.001):
    counter = itertools.count(0.0, step_seconds)
    return lambda: next(counter)


def _recorder(**kwargs) -> RunRecorder:
    kwargs.setdefault("client_message_id", "c-8f2a1b40")
    kwargs.setdefault("customer_message_count", 3)
    kwargs.setdefault("content_enabled", True)
    kwargs.setdefault("content_max_chars", 8000)
    kwargs.setdefault("clock", _ticking_clock())
    return RunRecorder("C-1024", **kwargs)


def _record_normal_run(recorder: RunRecorder) -> None:
    with recorder.step("extraction", "llm"):
        recorder.llm_call(
            purpose="extraction", model="gpt-4o-mini", duration_ms=820,
            prompt_tokens=412, completion_tokens=88,
            input_text="prompt " * 300, output_text="output " * 20,
        )
        recorder.tool_call(
            name="lookup_product_fact", arguments={"product": "plus", "field": "premium"},
            result_chars=90, duration_ms=12,
        )
    with recorder.step("state_transition", "rule") as step:
        step.note("Potential Interest -> Evaluation & Hesitation")
    with recorder.step("knowledge_retrieval", "retrieval"):
        pass
    with recorder.step("response_generation", "llm"):
        recorder.llm_call(
            purpose="response_generation", model="gpt-4o-mini", duration_ms=400,
            prompt_tokens=298, completion_tokens=64,
            input_text="prompt " * 200, output_text="reply " * 30,
        )


class TestPricing(unittest.TestCase):
    def test_gpt_4o_mini_is_priced_from_the_table(self):
        cost = cost_for("gpt-4o-mini", 1000, 500)
        self.assertEqual(cost.amount, Decimal("0.00045"))
        self.assertEqual(cost.currency, "USD")

    def test_a_dated_snapshot_prices_as_its_base_model(self):
        self.assertEqual(cost_for("gpt-4o-mini-2024-07-18", 1000, 500).amount, Decimal("0.00045"))

    def test_unknown_model_is_unpriced_not_free(self):
        self.assertIsNone(cost_for("some-unknown-model", 1000, 500))

    def test_no_tokens_is_unpriced_not_free(self):
        self.assertIsNone(cost_for("gpt-4o-mini", 0, 0))


class TestRunRecord(unittest.TestCase):
    """Acceptance 1: totals equal the sum of the parts; wire shape per §5.3."""

    def test_totals_equal_the_sum_of_the_parts(self):
        recorder = _recorder()
        _record_normal_run(recorder)
        run = recorder.finish()
        totals = run.totals()

        self.assertEqual(totals["agent_step_count"], len(run.steps))
        self.assertEqual(totals["llm_call_count"], 2)
        self.assertEqual(totals["tool_call_count"], 1)
        self.assertEqual(totals["total_tokens"], sum(c.total_tokens for c in run.llm_calls))
        self.assertEqual(totals["total_tokens"], 500 + 362)
        expected_cost = sum(c.cost.amount for c in run.llm_calls)
        self.assertEqual(run.total_cost.amount, expected_cost)
        self.assertAlmostEqual(totals["cost"]["amount"], float(expected_cost), places=6)

    def test_wire_shape_matches_interface_v1_section_5_3(self):
        recorder = _recorder()
        _record_normal_run(recorder)
        payload = recorder.finish().to_dict(include_content=True)

        self.assertEqual(
            set(payload),
            {
                "run_id", "opportunity_id", "client_message_id", "trigger",
                "customer_message_count", "started_at", "finished_at", "duration_ms",
                "status", "steps", "llm_calls", "tool_calls", "totals",
            },
        )
        self.assertTrue(payload["run_id"].startswith("ar-"))
        self.assertEqual(payload["trigger"], "customer_message")
        self.assertEqual(payload["status"], "ok")
        step = payload["steps"][0]
        self.assertEqual(set(step) - {"detail"}, {"index", "name", "kind", "duration_ms", "status"})
        call = payload["llm_calls"][0]
        self.assertEqual(
            set(call),
            {
                "index", "purpose", "model", "duration_ms", "prompt_tokens",
                "completion_tokens", "total_tokens", "cost", "input", "output",
            },
        )
        # 412 * 0.15 + 88 * 0.60 = 114.6 per million -> 0.0001146, reported at 6 dp
        self.assertEqual(call["cost"], {"amount": 0.000115, "currency": "USD"})
        self.assertEqual(set(payload["totals"]), {
            "agent_step_count", "llm_call_count", "tool_call_count", "total_tokens", "cost",
        })

    def test_steps_keep_their_order_ahead_of_the_tool_calls_they_made(self):
        recorder = _recorder()
        _record_normal_run(recorder)
        names = [s.name for s in recorder.finish().steps]
        self.assertEqual(names[:2], ["extraction", "tool.lookup_product_fact"])

    def test_status_rolls_up_from_the_steps(self):
        recorder = _recorder()
        with recorder.step("a", "rule"):
            pass
        self.assertEqual(recorder.finish().status, "ok")
        with recorder.step("b", "llm") as step:
            step.degrade("model unavailable: timeout")
        self.assertEqual(recorder.finish().status, "degraded")
        with self.assertRaises(RuntimeError):
            with recorder.step("c", "rule"):
                raise RuntimeError("boom")
        run = recorder.finish()
        self.assertEqual(run.status, "error")
        self.assertEqual(run.steps[-1].status, "error")

    def test_cost_is_absent_not_zero_when_unpriced(self):
        recorder = _recorder()
        with recorder.step("extraction", "llm"):
            recorder.llm_call(
                purpose="extraction", model="test", duration_ms=1,
                prompt_tokens=10, completion_tokens=2, input_text="x", output_text="y",
            )
        payload = recorder.finish().to_dict(include_content=False)
        self.assertNotIn("cost", payload["llm_calls"][0])
        self.assertNotIn("cost", payload["totals"])


class TestContentGate(unittest.TestCase):
    def test_chars_always_present_and_content_absent_when_withheld(self):
        recorder = _recorder(content_enabled=False)
        with recorder.step("extraction", "llm"):
            recorder.llm_call(
                purpose="extraction", model="gpt-4o-mini", duration_ms=1,
                prompt_tokens=1, completion_tokens=1,
                input_text="the customer's own words", output_text="out",
            )
        call = recorder.finish().to_dict(include_content=True)["llm_calls"][0]
        self.assertEqual(call["input"]["chars"], len("the customer's own words"))
        self.assertNotIn("content", call["input"])

    def test_to_dict_can_withhold_content_even_when_recorded(self):
        recorder = _recorder(content_enabled=True)
        with recorder.step("extraction", "llm"):
            recorder.llm_call(
                purpose="extraction", model="gpt-4o-mini", duration_ms=1,
                prompt_tokens=1, completion_tokens=1, input_text="secret", output_text="o",
            )
        run = recorder.finish()
        self.assertEqual(run.to_dict(include_content=True)["llm_calls"][0]["input"]["content"], "secret")
        self.assertNotIn("content", run.to_dict(include_content=False)["llm_calls"][0]["input"])

    def test_content_is_capped_but_chars_reports_the_original_length(self):
        recorder = _recorder(content_enabled=True, content_max_chars=10)
        with recorder.step("extraction", "llm"):
            recorder.llm_call(
                purpose="extraction", model="gpt-4o-mini", duration_ms=1,
                prompt_tokens=1, completion_tokens=1, input_text="x" * 50, output_text="o",
            )
        call = recorder.finish().llm_calls[0]
        self.assertEqual(call.input.chars, 50)
        self.assertEqual(len(call.input.content), 10)


class TestToolCallCounting(unittest.TestCase):
    """Acceptance 3: only model-selected calls count."""

    def test_retrieval_step_does_not_increment_tool_call_count(self):
        recorder = _recorder()
        with recorder.step("knowledge_retrieval", "retrieval"):
            pass
        run = recorder.finish()
        self.assertEqual(run.totals()["tool_call_count"], 0)
        self.assertEqual(run.steps[0].kind, "retrieval")

    def test_a_model_selected_call_increments_it_and_appears_as_a_tool_step(self):
        recorder = _recorder()
        recorder.tool_call(name="list_products", arguments={}, result_chars=400, duration_ms=3)
        run = recorder.finish()
        self.assertEqual(run.totals()["tool_call_count"], 1)
        self.assertEqual(run.steps[0].kind, "tool")
        self.assertEqual(run.steps[0].name, "tool.list_products")


class TestConsoleRendering(unittest.TestCase):
    """Acceptance 1: the block, and the warning form for degradations."""

    def test_a_normal_run_renders_one_block_with_every_column(self):
        recorder = _recorder()
        _record_normal_run(recorder)
        run = recorder.finish()
        text = render(run)
        lines = text.splitlines()

        self.assertTrue(lines[0].startswith(f"▶ run {run.run_id}  C-1024  customer_message  key=c-8f2a1b40"))
        self.assertEqual(len(lines), 1 + len(run.steps) + 1)
        extraction = lines[1]
        for column in ("0 extraction", "llm", "ms", "ok", "gpt-4o-mini", "412+88=500 tok", "$0.00011"):
            self.assertIn(column, extraction)
        self.assertIn("tool.lookup_product_fact", lines[2])
        self.assertIn("product=plus field=premium", lines[2])
        self.assertIn("retrieval", lines[4])
        footer = lines[-1]
        self.assertIn("✔ ok", footer)
        self.assertIn(f"{run.duration_ms}ms", footer)
        self.assertIn("2 llm", footer)
        self.assertIn("1 tool", footer)
        self.assertIn(f"{run.total_tokens} tok", footer)
        self.assertIn(f"${run.total_cost.amount:.5f}", footer)

    def test_a_degraded_run_renders_the_warning_form_naming_the_value(self):
        recorder = _recorder()
        violation = 'model returned intent="medical_question", not a member of Intent -> fell back to rules'
        with recorder.step("extraction", "llm") as step:
            step.degrade(violation)
        text = render(recorder.finish())
        self.assertIn("DEGRADED", text)
        self.assertIn("medical_question", text.splitlines()[1])
        self.assertIn("⚠ degraded", text.splitlines()[-1])

    def test_an_errored_run_renders_the_error_form(self):
        recorder = _recorder()
        with self.assertRaises(ValueError):
            with recorder.step("scoring", "rule"):
                raise ValueError("bad")
        text = render(recorder.finish())
        self.assertIn("ERROR", text)
        self.assertIn("✖ error", text.splitlines()[-1])
        self.assertIn("scoring raised", text.splitlines()[-1])

    def test_colour_is_off_by_default_in_render(self):
        recorder = _recorder()
        with recorder.step("a", "rule"):
            pass
        self.assertNotIn("\033[", render(recorder.finish()))
        self.assertIn("\033[", render(recorder.finish(), colour=True))
