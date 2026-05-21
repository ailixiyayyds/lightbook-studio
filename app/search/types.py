from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class MetadataSearchQuery:
    """Input to a metadata search provider."""

    title: str = ""
    original_title: str = ""
    authors: list[str] = field(default_factory=list)
    media_type: str = ""
    language_iso: str = ""


@dataclass(frozen=True)
class MetadataSearchCandidate:
    """A single search result from a metadata search provider."""

    title: str = ""
    original_title: str = ""
    authors: list[str] = field(default_factory=list)
    summary: str = ""
    cover_url: str = ""
    source_name: str = ""
    source_url: str = ""
    tags: list[str] = field(default_factory=list)
    genres: list[str] = field(default_factory=list)
