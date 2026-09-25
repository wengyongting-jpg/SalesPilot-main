#!/usr/bin/env python3
"""Runner for evals/conversation-scenarios.json against any CareSure backend
that implements POST /api/messages per docs/v0.0/api/interface-v1.md.

Stdlib only, so it runs against a backend without needing this repo's own
virtualenv installed alongside it.

Usage:
    python3 evals/run_evals.py --base-url http://127.0.0.1:8010
    python3 evals/run_evals.py --base-url http://127.0.0.1:8010 --only regression
    python3 evals/run_evals.py --base-url http://127.0.0.1:8010 --only escalation-complaint
    python3 evals/run_evals.py --list
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Optional

DEFAULT_FILE = Path(__file__).parent / "conversation-scenarios.json"


class Turn:
    def __init__(self, status_code: int, body: Optional[dict]):
        self.status_code = status_code
        self.body = body


def load_suite(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def post_message(base_url: str, payload: dict, timeout: float) -> Turn:
    req = urllib.request.Request(
        base_url.rstrip("/") + "/api/messages",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            body = json.loads(raw) if raw else None
            return Turn(resp.status, body)
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            body = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            body = None
        return Turn(exc.code, body)
    except urllib.error.URLError as exc:
        raise ConnectionError(f"could not reach {base_url}: {exc}") from exc


def get_json(base_url: str, path: str, timeout: float) -> Turn:
    req = urllib.request.Request(base_url.rstrip("/") + path, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return Turn(resp.status, json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            body = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            body = None
        return Turn(exc.code, body)
    except urllib.error.URLError as exc:
        raise ConnectionError(f"could not reach {base_url}: {exc}") from exc


def build_send_text(send: dict) -> str:
    if "text" in send:
        return send["text"]
    repeat = send["text_repeat"]
    return repeat["text"] * repeat["times"]


def check_turn_expectations(expect: dict, turn: Turn) -> list[tuple[bool, str]]:
    results: list[tuple[bool, str]] = []
    expected_status = expect.get("status_code", 200)
    results.append((turn.status_code == expected_status, f"status_code == {expected_status} (got {turn.status_code})"))

    if turn.status_code != expected_status or turn.body is None:
        return results

    body = turn.body

    if "human_takeover" in expect:
        want = expect["human_takeover"]
        got = body.get("human_takeover")
        results.append((got == want, f"human_takeover == {want} (got {got})"))

    if "product" in expect and "any" not in str(expect["product"]):
        want = expect["product"]
        got = body.get("product")
        results.append((got == want, f"product == {want!r} (got {got!r})"))

    if "generation_in" in expect:
        want = expect["generation_in"]
        got = body.get("generation")
        results.append((got in want, f"generation in {want} (got {got!r})"))

    reply = body.get("reply") or ""

    reply_lower = reply.lower()

    if "reply_contains_any" in expect:
        options = expect["reply_contains_any"]
        hit = any(opt.lower() in reply_lower for opt in options)
        results.append((hit, f"reply contains any of {options} (case-insensitive)"))

    if "reply_contains_all" in expect:
        options = expect["reply_contains_all"]
        missing = [opt for opt in options if opt.lower() not in reply_lower]
        results.append((not missing, f"reply contains all of {options} (case-insensitive)" + (f" (missing: {missing})" if missing else "")))

    if "reply_not_contains_any" in expect:
        options = expect["reply_not_contains_any"]
        hits = [opt for opt in options if opt.lower() in reply_lower]
        results.append((not hits, f"reply contains none of {options} (case-insensitive)" + (f" (found: {hits})" if hits else "")))

    if "quick_replies_count_between" in expect:
        lo, hi = expect["quick_replies_count_between"]
        count = len(body.get("quick_replies") or [])
        results.append((lo <= count <= hi, f"quick_replies count in [{lo},{hi}] (got {count})"))

    return results


_PREMIUM_PATTERN = re.compile(r"S\$\s?[\d,]+")


def check_global_invariants(invariants: list[dict], turn: Turn) -> list[tuple[bool, str]]:
    if turn.body is None:
        return []
    body = turn.body
    reply = body.get("reply") or ""
    results: list[tuple[bool, str]] = []

    for inv in invariants:
        inv_id = inv["id"]
        if inv_id == "no-internal-vocabulary-leak":
            hits = [tok for tok in inv["values"] if tok in reply]
            results.append((not hits, f"[invariant:{inv_id}] no internal vocabulary in reply" + (f" (leaked: {hits})" if hits else "")))
        elif inv_id == "customer-response-allowlist":
            if turn.status_code != 200:
                continue
            allowed = {
                "reply", "human_takeover", "message", "facts", "quick_replies",
                "customer_question", "client_message_id",
            }
            extra = sorted(set(body) - allowed)
            message = body.get("message") or {}
            allowed_message = {
                "id", "ts", "role", "author", "rep_name", "generation", "text",
                "client_message_id",
            }
            extra_message = sorted(set(message) - allowed_message) if isinstance(message, dict) else []
            question = body.get("customer_question")
            allowed_question = {"field", "prompt", "options", "allow_other"}
            extra_question = (
                sorted(set(question) - allowed_question)
                if isinstance(question, dict) else []
            )
            extra_options = []
            if isinstance(question, dict):
                for option in question.get("options") or []:
                    if isinstance(option, dict):
                        extra_options.extend(sorted(set(option) - {"id", "label"}))
            ok = not extra and not extra_message and not extra_question and not extra_options
            detail = []
            if extra:
                detail.append(f"extra top-level fields: {extra}")
            if extra_message:
                detail.append(f"extra message fields: {extra_message}")
            if extra_question:
                detail.append(f"extra question fields: {extra_question}")
            if extra_options:
                detail.append(f"extra question-option fields: {extra_options}")
            results.append((ok, f"[invariant:{inv_id}] customer response follows the allowlist" + (f" ({'; '.join(detail)})" if detail else "")))
        elif inv_id == "quick-replies-bounded":
            chips = body.get("quick_replies") or []
            over_count = len(chips) > 3
            long_labels = [c.get("label", "") for c in chips if len(c.get("label", "")) > 24]
            ok = not over_count and not long_labels
            detail = []
            if over_count:
                detail.append(f"{len(chips)} chips > 3")
            if long_labels:
                detail.append(f"labels too long: {long_labels}")
            results.append((ok, f"[invariant:{inv_id}] quick replies bounded" + (f" ({'; '.join(detail)})" if detail else "")))
        elif inv_id == "premium-figure-implies-disclaimer":
            if "premium" in reply.lower() and _PREMIUM_PATTERN.search(reply):
                ok = inv["value"] in reply
                results.append((ok, f"[invariant:{inv_id}] premium figure carries the disclaimer" + ("" if ok else " (disclaimer missing)")))
        elif inv_id == "no-agent-role":
            def has_agent_role(value: Any) -> bool:
                if isinstance(value, dict):
                    return any(
                        (key == "role" and item == "agent") or has_agent_role(item)
                        for key, item in value.items()
                    )
                if isinstance(value, list):
                    return any(has_agent_role(item) for item in value)
                return False

            ok = not has_agent_role(body)
            results.append((ok, f"[invariant:{inv_id}] no role=agent anywhere in the response"))

    return results


def check_admin_expectations(expect: dict, admin_body: dict) -> list[tuple[bool, str]]:
    results: list[tuple[bool, str]] = []
    if "state" in expect:
        want = expect["state"]
        got = admin_body.get("state")
        results.append((got == want, f"admin.state == {want!r} (got {got!r})"))
    if "product" in expect:
        want = expect["product"]
        got = admin_body.get("product")
        results.append((got == want, f"admin.product == {want!r} (got {got!r})"))
    if "qualification" in expect:
        want = expect["qualification"]
        got = admin_body.get("qualification")
        results.append((got == want, f"admin.qualification == {want!r} (got {got!r})"))
    if "churn_risk" in expect:
        want = expect["churn_risk"]
        got = admin_body.get("churn_risk")
        results.append((got == want, f"admin.churn_risk == {want} (got {got})"))
    if "expansion_contains" in expect:
        want = expect["expansion_contains"]
        got = admin_body.get("expansion") or []
        results.append((want in got, f"admin.expansion contains {want!r} (got {got})"))
    if "solicitation_count" in expect:
        want = expect["solicitation_count"]
        got = admin_body.get("solicitation_count")
        results.append((got == want, f"admin.solicitation_count == {want} (got {got})"))
    if "signals_contains" in expect:
        want = expect["signals_contains"]
        got = admin_body.get("signals") or []
        results.append((want in got, f"admin.signals contains {want!r} (got {got})"))
    return results


def run_scenario(base_url: str, scenario: dict, timeout: float, verbose: bool) -> tuple[bool, list[str]]:
    actor_ids: dict[str, str] = {}
    lines: list[str] = []
    is_known_issue = scenario.get("category") == "known_issue"
    all_ok = True

    def customer_id_for(actor: str) -> str:
        if actor not in actor_ids:
            actor_ids[actor] = f"eval-{scenario['id']}-{actor}-{uuid.uuid4().hex[:6]}"
        return actor_ids[actor]

    for i, turn_spec in enumerate(scenario["turns"], start=1):
        send = turn_spec["send"]
        actor = send.get("as", "default")
        customer_id = customer_id_for(actor)
        payload = {
            "customer_id": customer_id,
            "customer_name": "Eval Bot",
            "text": build_send_text(send),
        }
        if "client_message_id" in send:
            payload["client_message_id"] = send["client_message_id"]

        turn = post_message(base_url, payload, timeout)
        actor_note = f" [as: {actor}]" if actor != "default" else ""
        lines.append(f"  turn {i}{actor_note}: {payload['text'][:70]!r}")

        if is_known_issue:
            lines.append(f"    (known issue — reporting observed values only, not pass/fail)")
            if turn.body is not None:
                lines.append(f"    status={turn.status_code} product={turn.body.get('product')} human_takeover={turn.body.get('human_takeover')}")
                lines.append(f"    reply={turn.body.get('reply', '')[:120]!r}")
            else:
                lines.append(f"    status={turn.status_code} body=<none>")
            if turn_spec.get("observe_admin"):
                admin_turn = get_json(base_url, f"/api/admin/opportunities/{customer_id}", timeout)
                if admin_turn.body is not None:
                    a = admin_turn.body
                    lines.append(
                        f"    admin: state={a.get('state')!r} qualification={a.get('qualification')!r} "
                        f"solicitation_count={a.get('solicitation_count')} signals={a.get('signals')}"
                    )
            continue

        expect = turn_spec.get("expect", {})
        checks = check_turn_expectations(expect, turn)
        checks += check_global_invariants(scenario.get("_global_invariants", []), turn)

        if "admin_check" in turn_spec:
            admin_turn = get_json(base_url, f"/api/admin/opportunities/{customer_id}", timeout)
            if admin_turn.body is None:
                checks.append((False, f"admin_check: could not fetch /api/admin/opportunities/{customer_id} (status {admin_turn.status_code})"))
            else:
                checks += check_admin_expectations(turn_spec["admin_check"]["expect"], admin_turn.body)

        for passed, desc in checks:
            all_ok = all_ok and passed
            mark = "PASS" if passed else "FAIL"
            if verbose or not passed:
                lines.append(f"    [{mark}] {desc}")

    return (True if is_known_issue else all_ok), lines


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", help="Base URL of the backend under test, e.g. http://127.0.0.1:8010")
    parser.add_argument("--file", default=str(DEFAULT_FILE), help="Path to the eval scenarios JSON file")
    parser.add_argument("--only", help="Run only scenarios whose id or category matches this string")
    parser.add_argument("--timeout", type=float, default=10.0, help="Per-request timeout in seconds")
    parser.add_argument("--verbose", action="store_true", help="Print every assertion, not just failures")
    parser.add_argument("--list", action="store_true", help="List scenario ids and categories, then exit")
    args = parser.parse_args()

    suite = load_suite(Path(args.file))
    scenarios = suite["scenarios"]

    if args.list:
        for s in scenarios:
            tag = f" [{s['status']}]" if s.get("status") else ""
            print(f"{s['id']:55s} {s['category']}{tag}")
        return 0

    if not args.base_url:
        parser.error("--base-url is required unless --list is given")

    if args.only:
        scenarios = [s for s in scenarios if args.only in s["id"] or args.only == s["category"]]
        if not scenarios:
            print(f"No scenarios match --only {args.only!r}", file=sys.stderr)
            return 2

    global_invariants = suite.get("global_invariants", [])
    for s in scenarios:
        s["_global_invariants"] = global_invariants

    print(f"Running {len(scenarios)} scenario(s) against {args.base_url}\n")

    passed_count = 0
    failed_count = 0
    info_count = 0

    try:
        for scenario in scenarios:
            ok, lines = run_scenario(args.base_url, scenario, args.timeout, args.verbose)
            is_known_issue = scenario.get("category") == "known_issue"
            if is_known_issue:
                status = "INFO"
                info_count += 1
            elif ok:
                status = "PASS"
                passed_count += 1
            else:
                status = "FAIL"
                failed_count += 1
            print(f"[{status}] {scenario['id']} ({scenario['category']})")
            for line in lines:
                print(line)
            print()
    except ConnectionError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print(f"--- {passed_count} passed, {failed_count} failed, {info_count} informational (known issues) ---")
    return 1 if failed_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
