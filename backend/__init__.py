# -*- coding: utf-8 -*-
"""SalesPilot backend — CareSure AI sales assistant.

An agentic rebuild of the original `salespilot` package. The plan, the reasoning
and the phase-by-phase acceptance criteria are in `docs/v0.0/backend/backend-plan.md`; the wire
contract is `docs/v0.0/api/interface-v1.md`.

Layering
--------

Nine packages, each with one job. The import direction is one-way, and it is
enforced by `backend/tests/test_architecture.py` rather than by convention:

    domain  <-  kernel  <-  services  ->  agent  ->  providers
                              |             |
                           storage     observability
                              ^
                             api

    domain          pure data; the single source of truth for every wire string.
                    Imports nothing else. Standard library only.
    kernel          deterministic business core: state machine, scoring,
                    priority, next best action, HITL, quick replies. Imports
                    only `domain`. Standard library only. Never instrumented.
    knowledge       the product knowledge base and its retrievers.
    agent           the agentic shell. THE ONLY package permitted to call a
                    model or to import the agent framework.
    observability   agent run records, cost accounting, terminal rendering.
                    Never imported by `domain` or `kernel`.
    providers       model transports. Any OpenAI-compatible endpoint, plus an
                    offline provider that forces the deterministic path.
    storage         repositories. In-memory and SQLite.
    services        use-cases. Owns transactions, idempotency and run records.
                    The only package that writes storage.
    api             the HTTP surface, split by visibility tier. The customer
                    schemas have no shape for sensitive data, so leaking it is
                    impossible rather than merely discouraged.

Two rules carry the design, and both exist because of defects found in the
original build:

1. The model may propose, never decide. Every business decision — state, score,
   priority, next best action, escalation — is made in `kernel`, which the model
   cannot reach.
2. Every schema the model sees is generated from `domain.enums`. A value the
   domain does not accept fails validation and is recorded as a model contract
   violation; it is never silently downgraded.
"""
import sys

__version__ = "1.0.0-dev"

# The codebase uses `X | None` annotations and `sys.stdlib_module_names`, which
# require 3.10+. Fail with a sentence instead of a TypeError from deep inside an
# import. Kept Python-2-safe so even an ancient interpreter reaches the message.
_MIN_PYTHON = (3, 10)
if sys.version_info < _MIN_PYTHON:
    _current = ".".join(str(part) for part in sys.version_info[:3])
    raise SystemExit(
        "The SalesPilot backend requires Python 3.10 or newer, but you are "
        "running Python " + _current + ".\n"
        "Start it with a newer interpreter, for example:\n"
        "    py -3.12 -m backend --serve\n"
    )
