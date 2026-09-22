# -*- coding: utf-8 -*-
"""Use-cases. The application layer.

Owns what a single request means end to end: idempotency, the order of
operations, persistence, and recording the agent run. Composes `agent` (which
understands and words) with `kernel` (which decides) -- neither of which knows
about the other.

The only package that writes storage.
"""
