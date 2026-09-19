# -*- coding: utf-8 -*-
"""CLI entry point: chat simulation, demo, seeding and the HTTP API server."""
import argparse

from . import config
from .agent import SalesPilotAgent
from .dashboard import render_customer, render_dashboard
from .demo import run_demo
from .seed import seed_demo_data
from .storage import Repository, SqliteRepository

BANNER = r"""
============================================================
  SalesPilot - CareSure AI Sales Assistant (demo build)
------------------------------------------------------------
  Talk to the assistant just like WhatsApp.
  Commands:
    /dashboard   show the sales queue
    /customer    show current customer opportunity view
    /cases       list human escalation cases
    /reset       start the conversation over
    /help        show this help
    /quit        exit
============================================================
"""

HELP_TEXT = (
    "Type a customer message to chat, or use: "
    "/dashboard, /customer, /cases, /reset, /help, /quit"
)


def build_agent(args: argparse.Namespace) -> SalesPilotAgent:
    """Construct an agent from CLI flags (repository / retrieval / generator)."""
    repository = (
        SqliteRepository(args.db) if args.db else Repository()
    )

    retriever = None
    if args.semantic:
        from .knowledge import SemanticKnowledgeRetriever

        retriever = SemanticKnowledgeRetriever()

    response_generator = None
    llm_client = None
    if args.llm:
        from .providers import build_llm_client
        from .response import LLMResponseGenerator

        llm_client = build_llm_client()
        response_generator = LLMResponseGenerator(llm_client)

    return SalesPilotAgent(
        repository=repository,
        retriever=retriever,
        response_generator=response_generator,
        llm_client=llm_client,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="salespilot",
        description="CareSure AI sales assistant - runnable demo build",
    )
    parser.add_argument(
        "--demo", action="store_true",
        help="run the scripted demo conversations and print the sales dashboard",
    )
    parser.add_argument(
        "--dashboard", action="store_true",
        help="build the scripted demo data then only show the dashboard",
    )
    parser.add_argument(
        "--seed", action="store_true",
        help="seed the scripted demo data into the repository (use with --db)",
    )
    parser.add_argument(
        "--serve", action="store_true",
        help="start the FastAPI HTTP service",
    )
    parser.add_argument("--host", default=config.API_HOST, help="API host")
    parser.add_argument("--port", type=int, default=config.API_PORT, help="API port")
    parser.add_argument(
        "--db", default=None,
        help="path to a SQLite database file (default: in-memory repository)",
    )
    parser.add_argument(
        "--semantic", action="store_true",
        help="use the offline embedding/vector-store retriever instead of rules",
    )
    parser.add_argument(
        "--llm", action="store_true",
        help="use the configured LLM for reply phrasing (env vars; falls back "
             "to templates when unavailable)",
    )
    args = parser.parse_args(argv)

    if args.demo or args.dashboard:
        run_demo(build_agent(args))
        return 0

    if args.seed and not args.serve:
        agent = build_agent(args)
        print("Seeding demo data...")
        summary = seed_demo_data(agent)
        print(summary)
        print(render_dashboard(agent.repo))
        return 0

    if args.serve:
        return _serve(args)

    return _interactive(build_agent(args))


def _serve(args: argparse.Namespace) -> int:
    try:
        import uvicorn
        from .api import create_app
    except ImportError:
        print(
            "The API server needs FastAPI and Uvicorn.\n"
            "Install them with:  py -3 -m pip install -r requirements.txt"
        )
        return 1

    agent = build_agent(args)
    if args.seed and not agent.repo.list_opportunities():
        print("Seeding demo data...")
        print(seed_demo_data(agent))
    app = create_app(agent=agent)
    print(f"SalesPilot API listening on http://{args.host}:{args.port}  "
          f"(docs at /docs)")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


def _interactive(agent: SalesPilotAgent) -> int:
    print(BANNER)
    customer_id = "C-DEMO"
    customer_name = "Demo Customer"

    while True:
        try:
            text = input("\nCustomer > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            return 0

        if not text:
            continue

        if text.startswith("/"):
            should_exit = _handle_command(text, agent, customer_id)
            if should_exit:
                return 0
            continue

        result = agent.handle_message(customer_id, customer_name, text)
        print(f"\nSalesPilot > {result.reply}")
        print(
            f"   [state] {result.state_change} | "
            f"[signals] {', '.join(s.value for s in result.detection.signals) or '-'} | "
            f"[score] {result.score.total}/100 {result.score.priority.value} | "
            f"[action] {result.next_best_action.action}"
        )
        if result.case:
            print(f"   [HITL] Case {result.case.id}: {result.case.reason}")


def _handle_command(text: str, agent: SalesPilotAgent, customer_id: str) -> bool:
    """Return True when the app should exit."""
    command = text.lower()

    if command in ("/quit", "/exit"):
        print("Bye.")
        return True

    if command == "/help":
        print(HELP_TEXT)
    elif command == "/dashboard":
        print(render_dashboard(agent.repo))
    elif command == "/customer":
        opp = agent.repo.get_opportunity(customer_id)
        print(render_customer(opp) if opp else "No conversation yet.")
    elif command == "/cases":
        cases = agent.repo.list_cases()
        if not cases:
            print("No human escalation cases yet.")
        for case in cases:
            print(
                f"[{case.status.value}] {case.id} | {case.customer_name} | "
                f"{case.reason} | Action: {case.recommended_action}"
            )
    elif command == "/reset":
        agent.repo.delete_opportunity(customer_id)
        print("Conversation reset.")
    else:
        print(f"Unknown command: {text}. Type /help.")
    return False
