# -*- coding: utf-8 -*-
"""Model contract violations: the model returned something the domain rejects.

This is the third failure class named in this package's docstring, and the one that
was completely invisible in the previous build. A misconfigured provider at least
produced a fallback that could be inferred from a response field; a model answering
with a value outside the enum was silently replaced by a default, which disabled
three escalation triggers without a single log line.

A violation is not an error. The request succeeds, the run continues, and the
rule-based peer or a default fills in. What changes is that the substitution is
**recorded and named**, so it can be seen in the terminal, surfaced in the admin
timeline, and counted.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ModelViolation:
    """One value the model produced that the domain does not accept.

    `allowed` is carried rather than looked up later so the record stays readable
    once the enum has moved on — a violation from last week should still explain
    what was permitted at the time.
    """

    field: str
    value: str
    allowed: list[str] = field(default_factory=list)
    message: str = ""

    def __post_init__(self) -> None:
        if not self.message:
            # Frozen dataclass: set through the same channel the generated
            # __init__ uses.
            object.__setattr__(
                self,
                "message",
                f"model returned {self.field}={self.value!r}, which is not a "
                f"permitted value; ignored",
            )

    def describe(self) -> str:
        """One line for a terminal or a log.

        ASCII only, including the elision marker. A Windows console at its default
        code page mangles a horizontal ellipsis, and this line is read precisely when
        something has gone wrong — it must not itself look broken. The common case is
        the truncating one, since the enums it reports on have eleven and fourteen
        members.
        """
        shown = ", ".join(self.allowed[:6])
        suffix = ", ..." if len(self.allowed) > 6 else ""
        return f"{self.message} (allowed: {shown}{suffix})"
