from __future__ import annotations

from app.search.candidate_ranker import score_and_sort
from app.search.search_pipeline import _deduplicate
from app.search.types import MetadataSearchCandidate, MetadataSearchQuery


def _candidate(title: str, source_url: str = "", **kw: object) -> MetadataSearchCandidate:
    defaults: dict[str, object] = {
        "title": title,
        "source_url": source_url or f"https://example.com/{title.lower().replace(' ', '_')}",
        "source_name": "Test Source",
        "source_type": "library_metadata",
        "verified": True,
        "cover_url": "",
        "summary": "",
        "isbn": "",
        "publisher": "",
    }
    defaults.update(kw)
    return MetadataSearchCandidate(**{k: v for k, v in defaults.items() if k in MetadataSearchCandidate.__dataclass_fields__})


class TestDeduplicate:

    def test_removes_duplicate_urls(self) -> None:
        candidates = [
            _candidate("Test", "https://a.com/1"),
            _candidate("Test", "https://a.com/1"),
            _candidate("Test", "https://b.com/2"),
        ]
        result = _deduplicate(candidates)
        assert len(result) == 2

    def test_removes_duplicate_isbns(self) -> None:
        candidates = [
            _candidate("A", "https://a.com/1", isbn="978-X"),
            _candidate("B", "https://b.com/2", isbn="978-X"),
        ]
        result = _deduplicate(candidates)
        assert len(result) == 1

    def test_keeps_unique_candidates(self) -> None:
        candidates = [
            _candidate("A", "https://a.com/1"),
            _candidate("B", "https://b.com/2"),
            _candidate("C", "https://c.com/3"),
        ]
        result = _deduplicate(candidates)
        assert len(result) == 3


class TestScoreAndSort:

    def test_verified_first(self) -> None:
        candidates = [
            _candidate("A", source_type="search_result", verified=False),
            _candidate("B", source_type="library_metadata", verified=True),
        ]
        result = score_and_sort(MetadataSearchQuery(title=""), candidates)
        assert result[0].verified is True

    def test_with_cover_before_without(self) -> None:
        candidates = [
            _candidate("A", cover_url=""),
            _candidate("B", cover_url="https://example.com/cover.jpg"),
        ]
        result = score_and_sort(MetadataSearchQuery(title=""), candidates)
        assert result[0].cover_url

    def test_source_type_priority(self) -> None:
        candidates = [
            _candidate("A", source_type="search_result", source_url="https://a.com"),
            _candidate("B", source_type="official_publisher", source_url="https://b.com"),
            _candidate("C", source_type="library_metadata", source_url="https://c.com"),
        ]
        result = score_and_sort(MetadataSearchQuery(title=""), candidates)
        assert result[0].source_type == "official_publisher"

    def test_title_match_priority(self) -> None:
        candidates = [
            _candidate("Unrelated", source_url="https://x.com"),
            _candidate("My Manga Title", source_url="https://y.com"),
        ]
        result = score_and_sort(MetadataSearchQuery(title="My Manga Title"), candidates)
        assert result[0].title == "My Manga Title"

    def test_empty_returns_empty(self) -> None:
        assert score_and_sort(MetadataSearchQuery(title=""), []) == []


class TestCandidateSortingDoesNotInventUrls:

    def test_urls_are_preserved(self) -> None:
        candidates = [
            _candidate("A", source_url="https://real-a.example.com", cover_url="https://real-a.example.com/cover.jpg"),
            _candidate("B", source_url="https://real-b.example.com"),
        ]
        result = score_and_sort(MetadataSearchQuery(title="Test"), candidates)
        assert result[0].source_url == candidates[0].source_url or result[0].source_url == candidates[1].source_url
        assert result[1].source_url == candidates[0].source_url or result[1].source_url == candidates[1].source_url

    def test_no_new_urls_added(self) -> None:
        original_urls = {"https://a.com", "https://b.com"}
        candidates = [
            _candidate("A", source_url="https://a.com"),
            _candidate("B", source_url="https://b.com"),
        ]
        result = score_and_sort(MetadataSearchQuery(title="Test"), candidates)
        result_urls = {c.source_url for c in result}
        assert result_urls == original_urls
