# -*- coding: utf-8 -*-
"""Command-line entry point.

Subcommands arrive with the phases that implement them (see
`docs/v0.0/backend/backend-plan.md` §9). `--probe` is useful from P0 onward because knowing
what model access is actually configured is the first thing to establish.
"""
from __future__ import annotations

import argparse

from . import __version__, config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m backend",
        description="SalesPilot backend — CareSure AI sales assistant.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument(
        "--probe", action="store_true",
        help="report the effective configuration and model reachability",
    )
    parser.add_argument("--serve", action="store_true", help="start the HTTP API")
    parser.add_argument("--demo", action="store_true", help="run the scripted demo")
    parser.add_argument("--seed", action="store_true", help="seed demo data")
    parser.add_argument("--host", default=config.API_HOST)
    parser.add_argument("--port", type=int, default=config.API_PORT)
    parser.add_argument("--db", default=None, help=f"SQLite path (default: {config.DEFAULT_DB_PATH})")
    return parser


def _print_configuration() -> None:
    print(f"SalesPilot backend {__version__}  [REBUILD IN PROGRESS - not usable yet]")
    for key, value in config.describe().items():
        print(f"  {key:<20} {value}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.probe:
        _print_configuration()
        from .observability import logging as run_logging

        run_logging.configure()  # proves the log location is writable before serving
        _print_probe()
        return 0

    if args.demo:
        _print_configuration()
        return _run_demo()

    if args.seed and not args.serve:
        _print_configuration()
        return _run_seed(args.db)

    if args.serve:
        _print_configuration()
        return _run_serve(args.host, args.port, args.db, seed_first=args.seed)

    _print_configuration()
    print("\nNothing to do. Try --probe, --demo or --seed.")
    return 0


def _run_demo() -> int:
    from .services.conversation import build_service
    from .services.seeding import render_summary, seed
    from .storage import MemoryRepository

    repo = MemoryRepository()
    service = build_service(repo)
    print()
    outcome = seed(service)
    print()
    print(render_summary(repo))
    print(f"\nseeded {outcome['messages_seeded']} messages, {outcome['human_cases']} human case(s)")
    return 0


def _print_probe() -> None:
    """The compatibility verdict: what model access was actually found.

    Printed at `--probe` and again at startup, because "it ran offline and
    nobody noticed" is the failure this line exists to prevent.
    """
    from .providers.probe import probe

    result = probe()
    reachable = result.reachable
    status = "n/a" if reachable is None else ("yes" if reachable else "no")
    print(f"  model reachability   {status} — {result.detail}")
    verdict = (
        "offline — rule-based extraction and template replies; every run reports degraded"
        if reachable is not True
        else "model access available — OpenAI-compatible endpoint reachable"
    )
    print(f"  verdict              {verdict}")


def _run_serve(host: str, port: int, db_path: str | None, *, seed_first: bool) -> int:
    try:
        import uvicorn
    except ImportError:
        print("\nuvicorn is not installed. Run: pip install -r requirements.txt")
        return 1
    from .api.app import create_app
    from .observability import logging as run_logging
    from .services.conversation import build_service
    from .services.seeding import seed
    from .storage import SqliteRepository

    run_logging.configure()
    _print_probe()
    repo = SqliteRepository(db_path)
    service = build_service(repo)
    if seed_first:
        outcome = seed(service)
        print(
            f"\nseeded {outcome['messages_seeded']} messages" if outcome["seeded"]
            else f"\nnot seeded: {outcome['reason']}"
        )
    app = create_app(repo, conversation=service)
    print(f"\nSalesPilot backend listening on http://{host}:{port}  (docs at /docs, db {repo.path})")
    try:
        uvicorn.run(app, host=host, port=port, log_level="info")
    finally:
        repo.close()
    return 0


def _run_seed(db_path: str | None) -> int:
    from .services.conversation import build_service
    from .services.seeding import seed
    from .storage import SqliteRepository

    repo = SqliteRepository(db_path)
    try:
        outcome = seed(build_service(repo))
    finally:
        repo.close()
    if outcome["seeded"]:
        print(
            f"\nseeded {outcome['customers_seeded']} customers / {outcome['messages_seeded']} messages "
            f"into {repo.path}"
        )
    else:
        print(f"\nnot seeded: {outcome['reason']} ({repo.path})")
    return 0
