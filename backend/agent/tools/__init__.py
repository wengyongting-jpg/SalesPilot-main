# -*- coding: utf-8 -*-
"""The tool surface: what the model is allowed to do.

Signatures and argument types derive from `backend.domain.enums`, so a tool call
carrying a value the domain rejects fails validation instead of being coerced.

`request_human_handoff` only *proposes* an escalation. `backend.kernel.hitl`
decides. The model cannot open a case, move a state or change a score.
"""
