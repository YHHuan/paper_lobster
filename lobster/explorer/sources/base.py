"""Base classes for v3 source adapters."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RawFind:
    """A raw item discovered by a source adapter, ready for digester/extract."""

    source_type: str            # 'pubmed' | 'biorxiv' | 'arxiv' | 'blog' | 'twitter'
    title: str | None
    url: str | None
    content: str | None         # abstract / body / tweet text
    source_id: str | None = None    # PMID, DOI, arXiv id, etc.
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class OpenQuestion:
    """Mirror of the open_questions DB row used by Forage."""

    id: int | None
    question: str
    soul_anchor: str | None = None
    expected_source_types: list[str] = field(default_factory=list)
    priority: float = 0.5
    reasoning: str | None = None

    @classmethod
    def from_row(cls, row: dict) -> "OpenQuestion":
        return cls(
            id=row.get("id"),
            question=row.get("question", ""),
            soul_anchor=row.get("soul_anchor"),
            expected_source_types=row.get("expected_source_types") or [],
            priority=row.get("priority", 0.5),
            reasoning=row.get("reasoning"),
        )


class Source(ABC):
    """Abstract source adapter."""

    name: str = "base"

    @abstractmethod
    async def search(self, question: OpenQuestion, max_results: int = 5) -> list[RawFind]:
        ...

    async def close(self):
        pass
