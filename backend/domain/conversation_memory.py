"""Versioned, source-linked recall data for one opportunity."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class MemoryFact:
    text: str
    source_message_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        # A surviving source ID proves only that the referenced message exists.
        # It does not prove that the message entails this generated summary.
        return {
            "text": self.text,
            "source_message_ids": list(self.source_message_ids),
            "verification_status": "unverified",
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "MemoryFact":
        return cls(
            text=str(value.get("text", ""))[:240],
            source_message_ids=[
                str(item)[:80] for item in value.get("source_message_ids", [])[:5]
            ],
        )


@dataclass
class ConversationMemory:
    version: int = 1
    facts: list[MemoryFact] = field(default_factory=list)
    covered_message_ids: list[str] = field(default_factory=list)
    through_message_id: str | None = None
    updated_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "facts": [fact.to_dict() for fact in self.facts],
            "covered_message_ids": list(self.covered_message_ids),
            "through_message_id": self.through_message_id,
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "ConversationMemory":
        if not value:
            return cls()
        try:
            updated_at = datetime.fromisoformat(value["updated_at"])
        except (KeyError, TypeError, ValueError):
            updated_at = datetime.now()
        return cls(
            version=int(value.get("version", 1)),
            facts=[MemoryFact.from_dict(item) for item in value.get("facts", [])[:10]],
            covered_message_ids=[
                str(item)[:80] for item in value.get("covered_message_ids", [])[:30]
            ],
            through_message_id=(
                str(value["through_message_id"])[:80]
                if value.get("through_message_id") is not None else None
            ),
            updated_at=updated_at,
        )
