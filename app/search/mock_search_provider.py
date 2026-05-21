from __future__ import annotations

import hashlib

from app.search.provider import BaseMetadataSearchProvider
from app.search.types import MetadataSearchCandidate, MetadataSearchQuery


class MockSearchProvider(BaseMetadataSearchProvider):
    """Offline search provider that returns mock candidates for GUI and testing.

    Does not make any network requests. Generates 1-2 plausible candidates
    based on the query title and media type.
    """

    name = "mock"

    def search(self, query: MetadataSearchQuery) -> list[MetadataSearchCandidate]:
        title = (query.title or query.original_title or "").strip()
        if not title:
            return []

        candidates = [_primary_candidate(title, query)]
        if _should_return_second(title):
            candidates.append(_secondary_candidate(title, query))
        return candidates


def _primary_candidate(title: str, query: MetadataSearchQuery) -> MetadataSearchCandidate:
    media_label = "轻小说" if query.media_type == "novel" else "漫画"
    source_name = "Mock 资料库"
    return MetadataSearchCandidate(
        title=title,
        original_title=query.original_title or title,
        authors=list(query.authors) if query.authors else ["佚名"],
        summary=f"《{title}》是一部{media_label}作品。",
        cover_url=f"mock://cover/{_stable_hash(title)}/primary.jpg",
        source_name=source_name,
        source_url=f"mock://source/{_stable_hash(title)}",
        tags=_mock_tags(title, query),
        genres=_mock_genres(query),
    )


def _secondary_candidate(title: str, query: MetadataSearchQuery) -> MetadataSearchCandidate:
    media_label = "轻小说" if query.media_type == "novel" else "漫画"
    source_name = "Mock 社区"
    return MetadataSearchCandidate(
        title=title,
        original_title=query.original_title or title,
        authors=list(query.authors) if query.authors else ["未知作者"],
        summary=f"《{title}》是一部广受好评的{media_label}作品，值得收藏。",
        cover_url=f"mock://cover/{_stable_hash(title)}/secondary.jpg",
        source_name=source_name,
        source_url=f"mock://source/{_stable_hash(title)}/community",
        tags=_mock_tags(title, query),
        genres=_mock_genres(query),
    )


def _mock_tags(title: str, query: MetadataSearchQuery) -> list[str]:
    if query.media_type == "novel":
        return ["轻小说", "奇幻", "冒险"]
    return ["漫画", "校园", "日常"]


def _mock_genres(query: MetadataSearchQuery) -> list[str]:
    if query.media_type == "novel":
        return ["轻小说", "奇幻"]
    return ["漫画", "校园"]


def _should_return_second(title: str) -> bool:
    return len(title) > 3


def _stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:12]
