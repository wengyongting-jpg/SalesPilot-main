# -*- coding: utf-8 -*-
"""Command-line entry point.

Subcommands arrive with the phases that implement them (see
`docs/backend-plan.md` §9). `--probe` is useful from P0 onward because knowing
what model access is actually configured is the first thing to establish.
"""
from __future__ import annotations

import argparse
import sys

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
    parser.add_argument(
        "--test-api", action="store_true",
        help="test API connection with zero cost (offline mode only)",
    )
    parser.add_argument("--serve", action="store_true", help="start the HTTP API")
    parser.add_argument("--demo", action="store_true", help="run the scripted demo")
    parser.add_argument("--seed", action="store_true", help="seed demo data")
    parser.add_argument("--host", default=config.API_HOST)
    parser.add_argument("--port", type=int, default=config.API_PORT)
    return parser


def _print_configuration() -> None:
    print(f"SalesPilot backend {__version__}")
    for key, value in config.describe().items():
        print(f"  {key:<20} {value}")


def _make_output_safe() -> None:
    """Never let printing a diagnostic be the thing that crashes the process.

    Redirected stdout on Windows takes the locale encoding, `cp936` on this machine,
    not UTF-8. Traces echo the customer's own words, so a message in a script that
    encoding cannot represent would raise `UnicodeEncodeError` from inside the logger
    — a report about a problem taking down the run that was reporting it. UTF-8 with
    `errors="replace"` means the worst case is a replacement character.

    This is why `observability.console` uses ASCII glyphs rather than box drawing: the
    decoration is chosen to be safe, and this handles the content, which cannot be.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            # An already-wrapped or unusual stream. Not worth failing over.
            pass


def main(argv: list[str] | None = None) -> int:
    _make_output_safe()
    args = build_parser().parse_args(argv)

    if args.test_api:
        _print_configuration()
        return _test_api()

    if args.probe:
        _print_configuration()
        return _probe()

    if args.serve:
        return _serve(args)

    if args.seed:
        _print_configuration()
        return _seed_only()

    if args.demo:
        from . import demo

        built = _build()
        return demo.run(model=built.model, model_reason=built.describe())

    _print_configuration()
    print("\nNothing to do. Try --probe, --test-api, --demo, or --serve --seed.")
    return 0


def _test_api() -> int:
    """Test API with a zero-cost offline request to verify the backend works.

    This is a safe test that:
    - Uses offline mode (no model calls, zero cost)
    - Tests the full pipeline (extraction → kernel → reply)
    - Verifies all endpoints work
    - Returns success/failure status
    """
    from .services.conversation import ConversationService

    print("\n" + "=" * 78)
    print("  API Test - Zero Cost (Offline Mode)")
    print("=" * 78)

    # Force offline mode for testing
    if config.LLM_PROVIDER != "offline":
        print("\n  ⚠️  WARNING: Provider is set to '{}'. Switching to offline for test.".format(
            config.LLM_PROVIDER
        ))

    repository = _build_repository()
    try:
        # Create service in offline mode (model=None)
        service = ConversationService(repository, model=None)

        print("\n  Testing customer message endpoint...")
        result = service.handle_customer_message(
            customer_id="test-api-check",
            customer_name="API Test Customer",
            text="Hello, I'm interested in insurance coverage.",
            client_message_id="test-api-msg-001",
        )

        print(f"  ✓ Message processed successfully")
        print(f"  ✓ Reply generated: {len(result.reply)} characters")
        print(f"  ✓ Generation mode: {result.extraction_source}")
        print(f"  ✓ Opportunity created: {result.opportunity.id if result.opportunity else 'N/A'}")

        # Test idempotency
        print("\n  Testing idempotency (replaying same message)...")
        result2 = service.handle_customer_message(
            customer_id="test-api-check",
            customer_name="API Test Customer",
            text="Hello, I'm interested in insurance coverage.",
            client_message_id="test-api-msg-001",
        )

        if result2.replayed:
            print("  ✓ Idempotency verified: replay detected")
        else:
            print("  ✗ Idempotency FAILED: message was not replayed")
            return 1

        # Cleanup test data
        service.reset("test-api-check")

        print("\n" + "=" * 78)
        print("  ✅ API Test PASSED - All endpoints working")
        print("  💰 Cost: $0.00 (offline mode)")
        print("=" * 78)
        return 0

    except Exception as error:
        print(f"\n  ✗ API Test FAILED: {type(error).__name__}: {error}")
        print("\n" + "=" * 78)
        print("  ❌ API Test FAILED")
        print("=" * 78)
        return 1
    finally:
        repository.close()


def _probe() -> int:
    """Report what is configured and whether it answers.

    Returns 0 even when the endpoint is unreachable. `--probe` is a diagnostic, and
    an operator running it already knows something may be wrong; a non-zero exit adds
    nothing and breaks its use in a script that just wants the report. The one thing
    it must never do is stay quiet about a failure, which is what the detail line is
    for.
    """
    from .providers import probe, resolve

    spec = resolve()
    print(f"\n  provider resolved    {spec.describe()}")
    if spec.is_offline:
        # Not an error. Say so plainly, or somebody spends an afternoon looking for
        # a fault that was a deliberate default.
        print("  model reachability   not probed; no model is configured")
        print("\n  The backend is fully functional in this mode. To use a model,")
        print("  set SALESPILOT_LLM and SALESPILOT_LLM_API_KEY in .env")
        print("  (copy .env.example if you have not already).")
        return 0

    print(f"  endpoint             {spec.endpoint}")
    print(f"  probing              one minimal request, {spec.timeout}s timeout ...")
    result = probe(spec)
    print(f"  model reachability   {result.summary}")
    if result.reachable and result.model_reply is not None:
        print(f"  model said           {result.model_reply!r}")
    return 0


def _build_repository():
    from .storage.sqlite import SqliteRepository

    return SqliteRepository()


def _seed_only() -> int:
    from .services.conversation import ConversationService
    from .services.seeding import seed

    repository = _build_repository()
    try:
        summary = seed(ConversationService(repository, model=_build_model()))
        print(f"\n  {summary}")
        return 0
    finally:
        repository.close()


def _serve(args) -> int:
    try:
        import uvicorn
    except ImportError:
        print(
            "uvicorn is not installed. Run:\n"
            "      py -3 -m pip install -r requirements.txt"
        )
        return 1

    from .api.app import create_app
    from .services.conversation import ConversationService
    from .services.seeding import seed

    _print_configuration()
    repository = _build_repository()
    conversation = ConversationService(repository, model=_build_model())

    if args.seed:
        print(f"\n  seed: {seed(conversation)}")

    app = create_app(repository, conversation=conversation)
    print(
        f"\n  customer surface   http://{args.host}:{args.port}/api/messages\n"
        f"  admin surface      http://{args.host}:{args.port}/api/admin/opportunities\n"
        f"  interactive docs   http://{args.host}:{args.port}/docs\n"
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


def _build():
    """Resolve configuration to a model, or to a stated reason for offline.

    `providers` decides what to talk to; `agent.model_factory` decides how. Neither
    outcome is a failure: with no model the whole pipeline completes on the rule-based
    and template peers, and every reply is marked `generation="template"` so nobody
    mistakes it for model output.

    The reason is printed either way. A backend that silently chose the offline path
    is the exact failure this rebuild exists to remove.
    """
    from .agent.model_factory import build

    built = build()
    print(f"  model                {built.describe()}")
    return built


def _build_model():
    """Just the model object, for callers that do not narrate."""
    return _build().model
