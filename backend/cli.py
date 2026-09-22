# -*- coding: utf-8 -*-
"""Command-line entry point.

Subcommands arrive with the phases that implement them (see
`docs/backend-plan.md` §9). `--probe` is useful from P0 onward because knowing
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
    return parser


def _print_configuration() -> None:
    print(f"SalesPilot backend {__version__}  [REBUILD IN PROGRESS - not usable yet]")
    for key, value in config.describe().items():
        print(f"  {key:<20} {value}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.probe:
        _print_configuration()
        # Reachability probing lands with providers/probe.py in P3.
        print("  model reachability   not implemented yet (phase P3)")
        return 0

    if args.serve or args.demo or args.seed:
        _print_configuration()
        # Plain ASCII on purpose: a Windows console at its default code page mangles
        # a section sign, and a message about something being broken should not
        # itself look broken.
        print(
            "\nNot available yet. The backend is being rebuilt and has no HTTP "
            "surface, no model access and no storage at this point.\n"
            "  See backend/README.md for status, or docs/backend-plan.md section 9 "
            "for the phase that delivers this command.\n"
            "  For a working server right now, use the frozen build:\n"
            "      py -3 run.py --serve --seed"
        )
        return 1

    _print_configuration()
    print("\nNothing to do. Try --probe.")
    return 0
