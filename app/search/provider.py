from __future__ import annotations

from abc import ABC, abstractmethod

from app.search.types import MetadataSearchCandidate, MetadataSearchQuery


class BaseMetadataSearchProvider(ABC):
    """Abstract base for metadata search providers.

    Subclasses must set a `name` class attribute and implement `search`.
    """

    name: str

    @abstractmethod
    def search(self, query: MetadataSearchQuery) -> list[MetadataSearchCandidate]:
        """Search for metadata candidates without mutating state."""
