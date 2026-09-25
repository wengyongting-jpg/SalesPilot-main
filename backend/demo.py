# -*- coding: utf-8 -*-
"""The scripted demo: the whole pipeline in a terminal, no server, no browser.

Its job is to make the agent's reasoning **visible**. The two web surfaces show the
customer's side and the sales queue, but neither shows what happened in between, and
"the agent decided X" is not a claim anybody should accept on trust five minutes
before a deadline. So each turn prints the customer's message, the reply, and then
every intermediate the kernel produced: intent, signals, the state transition, the
score decomposed along both axes, the qualification verdict, the priority and the next
best action.

It runs the same `ConversationService` the API runs, on an in-memory repository, so
nothing here is a re-implementation and nothing it shows can be true of the demo but
false of the product. It reads whatever provider is configured: with a key the replies
are model-written and every line says `llm`; with none they are template-written and
every line says `template`. The intelligence is identical either way, which is the
clearest way to show that the kernel is not the model's to negotiate with.

Output is ASCII only. A Windows console at its default code page mangles box-drawing
characters, and a report about something working should not itself look broken.
"""
from __future__ import annotations

from typing import Optional

from . import config
from .services.seeding import SCRIPTS

WIDTH = 100
RULE = "-" * WIDTH
# Wide enough for the longest speaker label plus a separating space. At 22 the label
# `CareSure AI [template]` filled the column exactly and ran into the reply.
LABEL_WIDTH = 24


def run(*, model=None, model_reason: str = "", only: Optional[str] = None) -> int:
    """Replay the demo scripts through the real pipeline, narrating each turn."""
    from .services.analytics import AnalyticsService
    from .services.conversation import ConversationService
    from .storage.memory import InMemoryRepository

    repo = InMemoryRepository()
    # `trace=False`: this module renders the run itself, in line with the turn it
    # belongs to. Two renderers interleaving would make both harder to read.
    service = ConversationService(repo, model=model, trace=False)
    _quieten_run_log()

    mode = "model-backed" if model is not None else "offline"
    print(RULE)
    print(f"  SalesPilot demo  |  {mode}  |  {model_reason or config.LLM_PROVIDER}")
    print(f"  storage: in-memory (nothing written to {config.DEFAULT_DB_PATH.name})")
    print(RULE)

    scripts = SCRIPTS if only is None else {only: SCRIPTS[only]}
    for customer_id, script in scripts.items():
        _run_one(service, customer_id, script)

    _print_queue(repo)
    _print_analytics(AnalyticsService(repo).compute())
    return 0


def _quieten_run_log() -> None:
    """Stop the per-run log line from cutting across the turn it belongs to.

    Nothing is hidden. Every run logs a one-line summary, which in offline mode is at
    WARNING because the run genuinely is degraded — and that line landed between a
    turn's header and its content, making both unreadable. This module prints the same
    status, step count, tokens, cost and every degraded step itself, in place, so the
    summary is redundant here specifically. The log file still receives it.
    """
    import logging

    from .observability.logging import get_logger

    logger = get_logger()
    for handler in logger.handlers:
        if isinstance(handler, logging.StreamHandler) and not isinstance(
            handler, logging.FileHandler
        ):
            handler.setLevel(logging.ERROR)


def _run_one(service, customer_id: str, script: dict) -> None:
    print(f"\n{RULE}\n  {customer_id}  {script['name']}\n{RULE}")
    for turn, text in enumerate(script["messages"], start=1):
        result = service.handle_customer_message(
            customer_id=customer_id,
            customer_name=script["name"],
            text=text,
        )
        payload = result.to_dict()
        print(f"\n  turn {turn}")
        print(_wrap("customer", text))
        generation = (payload.get("message") or {}).get("generation", "?")
        # The AI label is a compliance red line, not decoration: the assistant is
        # never presented as a person. `docs/v0.0/product/product.md`.
        print(_wrap(f"CareSure AI [{generation}]", payload.get("reply", "")))
        for line in _intelligence(payload):
            print(f"      {line}")


def _intelligence(payload: dict) -> list[str]:
    """The internal view: everything the kernel derived, decomposed.

    Read off `to_dict()` - the same canonical payload the admin API projects from -
    so what the demo narrates cannot drift from what the API serves.
    """
    lines: list[str] = []
    det = payload.get("detection") or {}
    score = payload.get("score") or {}
    opp = payload.get("opportunity") or {}
    action = payload.get("next_best_action") or {}
    retrieval = payload.get("retrieval") or {}
    run = payload.get("agent_run") or {}

    signals = ", ".join(det.get("signals") or []) or "none"
    lines.append(
        f"detect    intent={det.get('intent')}  product={det.get('product')}  "
        f"source={payload.get('extraction_source')}"
    )
    lines.append(f"signals   {signals}")
    if det.get("solicitation"):
        lines.append("flag      solicitation detected")
    lines.append(f"state     {payload.get('state_change')}")

    if score:
        lines.append(
            f"fit       {score.get('fit_total')}  "
            f"(need {score.get('need_identified')} + "
            f"potential {score.get('product_potential')} + "
            f"expansion {score.get('expansion')})"
        )
        raw = score.get("behaviour_raw")
        total = score.get("behaviour_total")
        decay = "" if raw == total else f"  (raw {raw}, decayed for silence)"
        lines.append(
            f"behaviour {total}{decay}  "
            f"(intent {score.get('purchase_intent')} + "
            f"readiness {score.get('purchase_readiness')} + "
            f"engagement {score.get('engagement')})"
        )
        lines.append(
            f"headline  {score.get('total')} (display only; ranking uses priority)"
        )

    # The reason is only populated when the gate did something worth explaining, so
    # printing it unconditionally rendered a literal "None" on every healthy turn.
    qualification = opp.get("qualification")
    reason = opp.get("qualification_reason")
    lines.append(f"qualify   {qualification}" + (f" - {reason}" if reason else ""))
    lines.append(
        f"priority  {opp.get('priority')}  reply_mode={action.get('reply_mode')}"
    )
    lines.append(f"action    {action.get('action')} - {action.get('reason')}")
    if retrieval:
        lines.append(
            f"retrieval confidence={retrieval.get('confidence')}  "
            f"facts={len(retrieval.get('facts') or [])}"
        )
    if payload.get("case"):
        case = payload["case"]
        lines.append(f"escalate  case {case.get('id')} - {case.get('reason')}")
    if payload.get("quick_replies"):
        chips = ", ".join(chip["label"] for chip in payload["quick_replies"])
        lines.append(f"chips     {chips}")
    if run:
        # Read from `totals`, which is where the run puts them. Reaching for
        # `run["total_tokens"]` returns nothing and a `.get(..., 0)` default turns that
        # into a confident "0 tokens" - a demo quietly lying about cost, which is worse
        # than one that says nothing.
        totals = run.get("totals") or {}
        cost = totals.get("cost") or {}
        # Zero and unknown are different claims. `pricing.py` keeps them apart on
        # purpose: an unpriced gateway model reporting $0.00000 invites somebody to
        # budget against a number that means "no idea".
        money = (
            f"${cost.get('amount', 0.0):.5f}"
            if cost.get("pricing_known")
            else "cost unknown"
        )
        lines.append(
            f"run       {run.get('status')}  "
            f"{totals.get('agent_step_count', 0)} steps  "
            f"{totals.get('llm_call_count', 0)} model calls  "
            f"{totals.get('tool_call_count', 0)} tool calls  "
            f"{totals.get('total_tokens', 0)} tokens  {money}  "
            f"{run.get('duration_ms', 0)}ms"
        )
        for call in run.get("tool_calls") or []:
            # The model's own choices, which is the thing a demo of an agent is
            # actually about. Retrieval is a kernel step and is deliberately not
            # counted here - `interface-v1.md` §1.1 rule 2.
            arguments = ", ".join(
                f"{key}={value!r}" for key, value in (call.get("arguments") or {}).items()
            )
            lines.append(
                f"  tool      {call.get('name')}({arguments}) "
                f"-> {call.get('result_chars', 0)} chars"
            )
        for step in run.get("steps") or []:
            if step.get("status") != "ok":
                # `detail` is where a step's reason lives. Reaching for a `notes` list
                # found nothing and printed the bare status word instead, so every
                # degradation read as "extraction: degraded" - the shape of report
                # this whole layer exists to replace.
                lines.append(
                    f"  {step.get('status'):<9} {step.get('name')}: "
                    f"{step.get('detail') or 'no reason recorded'}"
                )
    return lines


def _print_queue(repo) -> None:
    print(f"\n{RULE}\n  SALES QUEUE (what a representative sees)\n{RULE}")
    print(
        f"  {'customer':<18}{'state':<22}{'fit':>4}{'beh':>5}"
        f"{'prio':>9}  qualification"
    )
    opportunities = sorted(
        repo.list_opportunities(),
        key=lambda opp: (opp.final_score or 0),
        reverse=True,
    )
    for opp in opportunities:
        fit = opp.score.fit_total if opp.score else 0
        behaviour = opp.score.behaviour_total if opp.score else 0
        priority = opp.priority.value if opp.priority else "-"
        flag = "" if opp.is_sellable else "  <- withheld from the queue"
        print(
            f"  {opp.customer_name[:17]:<18}{opp.state.value[:21]:<22}"
            f"{fit:>4}{behaviour:>5}{priority:>9}  "
            f"{opp.qualification.value}{flag}"
        )


def _print_analytics(stats: dict) -> None:
    print(f"\n{RULE}\n  ANALYTICS\n{RULE}")
    for key in (
        "total_opportunities",
        "by_priority",
        "average_score",
        "escalated_opportunities",
        "human_cases_open",
        "competitive_risks",
        "held",
    ):
        if key in stats:
            print(f"  {key:<26}{stats[key]}")
    print()


def _wrap(label: str, text: str) -> str:
    """One speaker line, indented so a long reply stays readable."""
    indent = " " * 6
    head = f"{indent}{label:<{LABEL_WIDTH}}"
    available = max(30, WIDTH - len(head))
    words, lines, current = (text or "").split(), [], ""
    for word in words:
        if current and len(current) + 1 + len(word) > available:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    if not lines:
        lines = [""]
    rendered = head + lines[0]
    for extra in lines[1:]:
        rendered += "\n" + indent + " " * LABEL_WIDTH + extra
    return rendered
