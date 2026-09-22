"""Run the multi-turn quality suite with explicit whole-suite budgets."""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .. import config
from ..agent import model_factory
from ..services.conversation import ConversationService
from ..storage.memory import InMemoryRepository
from .cases import CASES


def _matches(actual: dict, expected: dict) -> list[str]:
    errors: list[str] = []
    for key, wanted in expected.items():
        if key == "signals":
            present = set(actual.get("signals") or [])
            missing = [value for value in wanted if value not in present]
            if missing:
                errors.append(f"signals missing {missing!r}; got {sorted(present)!r}")
        elif actual.get(key) != wanted:
            errors.append(f"{key}: expected {wanted!r}, got {actual.get(key)!r}")
    return errors


def _labels(payload: dict) -> dict:
    detection = payload.get("detection") or {}
    opportunity = payload.get("opportunity") or {}
    return {
        "intent": detection.get("intent"),
        "product": detection.get("product"),
        "signals": detection.get("signals") or [],
        "solicitation": detection.get("solicitation"),
        "genuine_enquiry": detection.get("genuine_enquiry"),
        "cancellation": detection.get("cancellation"),
        "postponement": detection.get("postponement"),
        "state": opportunity.get("state"),
        "priority": opportunity.get("priority"),
        "qualification": opportunity.get("qualification"),
        "human_takeover": opportunity.get("human_takeover"),
    }


def _usage(payload: dict) -> dict:
    run = payload.get("agent_run") or {}
    totals = run.get("totals") or {}
    cost = totals.get("cost") or {}
    return {
        "status": run.get("status"),
        "llm_calls": totals.get("llm_call_count", 0),
        "tool_calls": totals.get("tool_call_count", 0),
        "tokens": totals.get("total_tokens", 0),
        "cost_usd": cost.get("amount", 0.0),
        "pricing_known": cost.get("pricing_known", True),
    }


def run_suite(*, use_model: bool, selected: set[str] | None = None,
              max_cases: int = 20, max_turns: int = 60,
              max_model_calls: int = 160, max_cost_usd: float = 1.0,
              attempt: int = 1) -> dict[str, Any]:
    built = model_factory.build() if use_model else None
    if use_model and (built is None or built.is_offline):
        reason = built.reason if built is not None else "model construction failed"
        raise RuntimeError(f"model evaluation requested but unavailable: {reason}")
    model = built.model if built is not None else None
    chosen = [case for case in CASES if selected is None or case["id"] in selected]
    chosen = chosen[:max_cases]
    report: dict[str, Any] = {
        "started_at": datetime.now().astimezone().isoformat(),
        "mode": "model" if use_model else "offline",
        "attempt": attempt,
        "provider": built.spec.provider if built is not None else "offline",
        "model": built.spec.model_name if built is not None else None,
        "limits": {
            "cases": max_cases, "turns": max_turns,
            "model_calls": max_model_calls, "cost_usd": max_cost_usd,
            "per_segment_tool_calls": config.LLM_MAX_TOOL_STEPS,
            "per_segment_requests": config.LLM_REQUEST_LIMIT,
            "per_segment_tokens": config.LLM_TOTAL_TOKEN_LIMIT,
            "per_segment_output_tokens": config.LLM_OUTPUT_TOKEN_LIMIT,
            "per_segment_cost_usd": float(config.LLM_COST_LIMIT_USD),
        },
        "totals": {"cases": 0, "passed": 0, "turns": 0, "llm_calls": 0,
                   "tool_calls": 0, "tokens": 0, "cost_usd": 0.0},
        "cases": [], "stopped_reason": None,
    }

    def budget_reason(*, before_turn: bool = False) -> str | None:
        totals = report["totals"]
        reserve_calls = 2 * config.LLM_REQUEST_LIMIT if before_turn and use_model else 0
        reserve_cost = (
            2 * float(config.LLM_COST_LIMIT_USD)
            if before_turn and use_model else 0.0
        )
        if totals["turns"] + int(before_turn) > max_turns:
            return "whole-suite turn budget reached"
        if totals["llm_calls"] + reserve_calls > max_model_calls:
            return "whole-suite model-call budget has no room for another turn"
        if totals["cost_usd"] + reserve_cost > max_cost_usd:
            return "whole-suite cost budget has no room for another turn"
        return None

    for case in chosen:
        if reason := budget_reason(before_turn=True):
            report["stopped_reason"] = reason
            break
        service = ConversationService(InMemoryRepository(), model=model, trace=False)
        item = {"id": case["id"], "name": case["name"], "attempt": attempt,
                "passed": True, "turns": [], "errors": []}
        last_labels: dict = {}
        for index, (text, expected) in enumerate(case["turns"], 1):
            totals = report["totals"]
            if reason := budget_reason(before_turn=True):
                report["stopped_reason"] = f"{reason} in {case['id']}"
                item["passed"] = False
                item["errors"].append(report["stopped_reason"])
                break
            result = service.handle_customer_message(
                customer_id=f"EVAL-{case['id']}", customer_name=case["name"], text=text
            ).to_dict()
            labels, usage = _labels(result), _usage(result)
            errors = _matches(labels, expected)
            item["turns"].append({"turn": index, "text": text, "expected": expected,
                                  "actual": labels, "errors": errors,
                                  "extraction_source": result.get("extraction_source"),
                                  "usage": usage, "agent_run": result.get("agent_run")})
            item["passed"] = item["passed"] and not errors
            item["errors"].extend(f"turn {index}: {error}" for error in errors)
            last_labels = labels
            totals["turns"] += 1
            for total_key, usage_key in (("llm_calls", "llm_calls"), ("tool_calls", "tool_calls"), ("tokens", "tokens"), ("cost_usd", "cost_usd")):
                totals[total_key] += usage[usage_key]
            if use_model and usage["llm_calls"] and not usage["pricing_known"]:
                report["stopped_reason"] = "model pricing is unknown; cannot enforce the cost budget"
                item["passed"] = False
                item["errors"].append(report["stopped_reason"])
                break
        final_errors = _matches(last_labels, case["final"]) if last_labels else ["no final labels"]
        item["final_expected"] = case["final"]
        item["final_actual"] = last_labels
        item["errors"].extend(f"final: {error}" for error in final_errors)
        item["passed"] = item["passed"] and not final_errors
        report["cases"].append(item)
        report["totals"]["cases"] += 1
        report["totals"]["passed"] += int(item["passed"])
        if report["stopped_reason"]:
            break
    report["totals"]["cost_usd"] = round(report["totals"]["cost_usd"], 8)
    report["finished_at"] = datetime.now().astimezone().isoformat()
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run SalesPilot multi-turn evaluations")
    parser.add_argument("--model", action="store_true", help="use the configured live model")
    parser.add_argument("--case", action="append", dest="cases")
    parser.add_argument("--exclude-case", action="append", dest="excluded_cases")
    parser.add_argument("--max-cases", type=int, default=20)
    parser.add_argument("--max-turns", type=int, default=60)
    parser.add_argument("--max-model-calls", type=int, default=160)
    parser.add_argument("--max-cost-usd", type=float, default=1.0)
    parser.add_argument("--attempt", type=int, choices=(1, 2, 3), default=1)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    selected = set(args.cases) if args.cases else {case["id"] for case in CASES}
    selected -= set(args.excluded_cases or [])
    report = run_suite(use_model=args.model, selected=selected,
                       max_cases=args.max_cases, max_turns=args.max_turns,
                       max_model_calls=args.max_model_calls,
                       max_cost_usd=args.max_cost_usd, attempt=args.attempt)
    path = args.report or config.REPO_ROOT / "runtime" / "evals" / f"eval-{report['mode']}-{datetime.now():%Y%m%d-%H%M%S}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    totals = report["totals"]
    print(f"{report['mode']}: {totals['passed']}/{totals['cases']} cases passed; {totals['turns']} turns; {totals['llm_calls']} model calls; {totals['tool_calls']} tool calls; {totals['tokens']} tokens; ${totals['cost_usd']:.6f}")
    for item in report["cases"]:
        print(f"  {'PASS' if item['passed'] else 'FAIL'} {item['id']}")
        for error in item["errors"]:
            print(f"    {error}")
    if report["stopped_reason"]:
        print(f"STOPPED: {report['stopped_reason']}")
    print(f"report: {path}")
    return 0 if totals["passed"] == totals["cases"] and not report["stopped_reason"] else 1
