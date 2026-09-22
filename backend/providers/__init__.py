# -*- coding: utf-8 -*-
"""Model transports.

`openai_compatible` talks to any OpenAI-compatible endpoint, which is how the
organiser gateway is reached. `offline` provides no model at all and forces the
deterministic path. `probe` reports at startup what was actually found, so a
misconfigured key is visible immediately rather than as a silent degradation.

If an endpoint turns out not to be OpenAI-compatible, this package is the only
one that changes.
"""
