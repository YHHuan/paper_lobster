"""Base class + dataclass for config-driven feed explorers.

Distinct from `lobster/explorer/sources/base.py`:
  Source.search(question) → list[RawFind] (digester pipeline → extracts table)
  BaseFeedExplorer.fetch(config) → AsyncIterator[RawDiscovery] (Coordinator → discoveries table)
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator


@dataclass
class RawDiscovery:
    """Unified result from any feed explorer.

    metadata may include: upvotes, score, comments, published, author, external_url.
    """

    source_type: str
    source_name: str
    url: str
    title: str
    raw_text: str
    language: str = "en"
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseFeedExplorer(ABC):
    """Iterator-style interface so coordinators can stream items as they arrive."""

    name: str = "base"

    @abstractmethod
    def fetch(self, config: dict) -> AsyncIterator[RawDiscovery]:
        ...

    async def close(self):
        pass
