# -*- coding: utf-8 -*-
"""The agentic shell: the only package permitted to call a model.

Owns the loop, the system prompts and guardrails, the structured-output schemas
generated from `backend.domain.enums`, and the tool surface the model may call.

What the model decides: what to look up, what to ask, how to word a reply.
What the model never decides: state, score, priority, next best action, whether
to escalate. Those belong to `backend.kernel`, which this package does not even
import -- `backend.services` orchestrates the two.

If the agent framework is ever replaced, `runtime.py` is the only module that
changes. `backend/tests/test_architecture.py` enforces that containment.
"""
