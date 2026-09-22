# -*- coding: utf-8 -*-
"""Which model to talk to, and whether it answers.

This package holds no client and imports no agent framework. `resolve()` reads
configuration and returns a `ProviderSpec` — an endpoint, a model name, a credential
and a timeout, or an explicit reason there is nothing to call. `agent.model_factory`
is what turns a spec into something callable, because §4 rule 2 of
`docs/backend-plan.md` gives the framework import to `agent/` alone.

    providers/   decides *what* to talk to, and can say "nothing, because ..."
    agent/       decides *how* to talk to it

`probe` is the exception that proves the rule: it speaks the chat-completions
protocol directly over the standard library, so it tests the endpoint rather than
the framework, and still works when the framework is absent.

If an endpoint turns out not to be OpenAI-compatible, a sibling of `resolve` is
where that lands.
"""
from .base import ProviderSpec
from .probe import ProbeResult, probe
from .resolve import resolve

__all__ = ["ProviderSpec", "ProbeResult", "probe", "resolve"]
