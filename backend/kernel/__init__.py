# -*- coding: utf-8 -*-
"""Deterministic business core. The model can never reach it.

State machine, opportunity value score, priority bands, next best action, HITL
escalation and quick replies. Plain Python, standard library only, imports only
`backend.domain`.

Kept free of instrumentation on purpose: business rules must be readable and
unit-testable without a recorder, a provider or a database in scope.
"""
