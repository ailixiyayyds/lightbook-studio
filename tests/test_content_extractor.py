"""Tests for metadata content extractor."""

import pytest

from app.search.content_extractor import (
    ContentExtractionError,
    MetadataContentExtractor,
    _to_string_list,
)
from app.search.types import MetadataSearchCandidate, MetadataSearchQuery


class MockAiProvider:
    """Mock AI provider for testing."""

    name = "mock"
    model = "test-model"

    def __init__(self, response: str = "") -> None:
        self.response = response
        self.calls: list[tuple[str, str]] = []

    def extract_from_content(
        self,
        system_prompt: str,
        user_content: str,
    ) -> str:
        self.calls.append((system_prompt, user_content))
        return self.response


class MockRepository:
    """Mock repository for testing."""

    def __init__(self) -> None:
        self.logs: list[dict] = []

    def create_ai_request_log(
        self,
        *,
        book_id: int | None,
        task_id: str,
        request_type: str,
        provider: str,
        model: str = "",
        request_json: dict | None = None,
        response_text: str = "",
        parsed_json: dict | None = None,
        status: str = "",
        error_message: str = "",
        duration_ms: int = 0,
    ) -> dict:
        log = {
            "book_id": book_id,
            "task_id": task_id,
            "request_type": request_type,
            "provider": provider,
            "model": model,
            "request_json": request_json or {},
            "response_text": response_text,
            "parsed_json": parsed_json or {},
            "status": status,
            "error_message": error_message,
            "duration_ms": duration_ms,
        }
        self.logs.append(log)
        return log


def make_candidate(
    *,
    title: str = "Test Title",
    raw_content: str = "",
    raw_content_type: str = "extract",
    images: list[str] | None = None,
    categories: list[str] | None = None,
    extraction_status: str = "",
    cover_url: str = "",
    source_url: str = "https://example.com/test",
    source_name: str = "test",
    source_type: str = "",
    verified: bool = False,
) -> MetadataSearchCandidate:
    return MetadataSearchCandidate(
        title=title,
        source_name=source_name,
        source_url=source_url,
        source_type=source_type,
        verified=verified,
        cover_url=cover_url,
        raw_content=raw_content,
        raw_content_type=raw_content_type,
        images=images or [],
        categories=categories or [],
        extraction_status=extraction_status,
    )


def make_query(
    *,
    title: str = "Test Query",
) -> MetadataSearchQuery:
    return MetadataSearchQuery(title=title)


class TestMetadataContentExtractor:
    def test_skip_if_no_raw_content(self) -> None:
        provider = MockAiProvider(response='{"title": "Test"}')
        repo = MockRepository()
        extractor = MetadataContentExtractor(provider, repo)

        candidate = make_candidate(raw_content="")
        query = make_query()

        result = extractor.extract_from_candidate(query, candidate)

        assert result.extraction_status == ""
        assert len(provider.calls) == 0

    def test_skip_if_already_extracted(self) -> None:
        provider = MockAiProvider(response='{"title": "Test"}')
        repo = MockRepository()
        extractor = MetadataContentExtractor(provider, repo)

        candidate = make_candidate(
            raw_content="some content",
            extraction_status="extracted",
        )
        query = make_query()

        result = extractor.extract_from_candidate(query, candidate)

        assert result.extraction_status == "extracted"
        assert len(provider.calls) == 0

    def test_successful_extraction(self) -> None:
        ai_response = """
        {
            "title": "Clean Title",
            "original_title": "Original Title",
            "authors": ["Author One", "Author Two"],
            "publisher": "Test Publisher",
            "summary": "This is a story about...",
            "genres": ["漫画", "恋爱"],
            "tags": ["校园", "日常"],
            "match_assessment": {
                "is_likely_same_work": true,
                "reason": "Title matches query"
            }
        }
        """
        provider = MockAiProvider(response=ai_response)
        repo = MockRepository()
        extractor = MetadataContentExtractor(provider, repo)

        candidate = make_candidate(
            raw_content="This is the raw page content...",
            images=["https://example.com/cover.jpg"],
        )
        query = make_query()

        result = extractor.extract_from_candidate(query, candidate)

        assert result.extraction_status == "extracted"
        assert result.title == "Clean Title"
        assert result.original_title == "Original Title"
        assert result.authors == ["Author One", "Author Two"]
        assert result.publisher == "Test Publisher"
        assert result.summary == "This is a story about..."
        assert result.genres == ["漫画", "恋爱"]
        assert result.tags == ["校园", "日常"]
        assert len(repo.logs) == 1
        assert repo.logs[0]["request_type"] == "metadata_content_extraction"
        assert repo.logs[0]["status"] == "completed"

    def test_custom_max_content_length_limits_prompt(self) -> None:
        provider = MockAiProvider(response='{"title": "Test", "summary_zh": "简介"}')
        repo = MockRepository()
        extractor = MetadataContentExtractor(provider, repo, max_content_length=1200)

        candidate = make_candidate(raw_content="x" * 5000)
        query = make_query()

        extractor.extract_from_candidate(query, candidate)

        assert len(provider.calls) == 1
        user_content = provider.calls[0][1]
        assert '"raw_content": "' + ("x" * 1200) in user_content
        assert "内容已截断" in user_content
        assert "x" * 1300 not in user_content

    def test_cover_url_from_images(self) -> None:
        ai_response = """
        {
            "summary": "Test summary",
            "cover_url_candidates": ["https://example.com/real_cover.jpg"],
            "genres": [],
            "tags": []
        }
        """
        provider = MockAiProvider(response=ai_response)
        repo = MockRepository()
        extractor = MetadataContentExtractor(provider, repo)

        candidate = make_candidate(
            raw_content="content",
            images=[
                "https://example.com/cover1.jpg",
                "https://example.com/real_cover.jpg",
            ],
        )
        query = make_query()

        result = extractor.extract_from_candidate(query, candidate)

        # cover_url should be set from cover_url_candidates if in images
        assert result.cover_url == "https://example.com/real_cover.jpg"

    def test_cover_url_not_from_ai_if_not_in_images(self) -> None:
        ai_response = """
        {
            "summary": "Test summary",
            "cover_url_candidates": ["https://fake.com/cover.jpg"],
            "genres": [],
            "tags": []
        }
        """
        provider = MockAiProvider(response=ai_response)
        repo = MockRepository()
        extractor = MetadataContentExtractor(provider, repo)

        candidate = make_candidate(
            raw_content="content",
            images=["https://example.com/real_cover.jpg"],
            cover_url="",  # No existing cover
        )
        query = make_query()

        result = extractor.extract_from_candidate(query, candidate)

        # cover_url should NOT be set because AI URL is not in images
        assert result.cover_url == ""

    def test_failed_extraction(self) -> None:
        provider = MockAiProvider(response="not valid json")
        repo = MockRepository()
        extractor = MetadataContentExtractor(provider, repo)

        candidate = make_candidate(raw_content="content")
        query = make_query()

        result = extractor.extract_from_candidate(query, candidate)

        assert result.extraction_status == "failed"
        assert result.extraction_error != ""
        assert len(repo.logs) == 1
        assert repo.logs[0]["status"] == "failed"

    def test_is_likely_same_work_false(self) -> None:
        ai_response = """
        {
            "summary": "Different work with same name",
            "genres": [],
            "tags": [],
            "match_assessment": {
                "is_likely_same_work": false,
                "reason": "This is a different manga with the same title"
            }
        }
        """
        provider = MockAiProvider(response=ai_response)
        repo = MockRepository()
        extractor = MetadataContentExtractor(provider, repo)

        candidate = make_candidate(raw_content="content")
        query = make_query()

        result = extractor.extract_from_candidate(query, candidate)

        assert result.extraction_status == "extracted"
        assert result.extraction_json["match_assessment"]["is_likely_same_work"] is False
        assert "不同" in result.extraction_json["match_assessment"]["reason"] or "different" in result.extraction_json["match_assessment"]["reason"].lower()

    def test_preserves_source_url(self) -> None:
        ai_response = """
        {
            "summary": "Test",
            "genres": [],
            "tags": []
        }
        """
        provider = MockAiProvider(response=ai_response)
        repo = MockRepository()
        extractor = MetadataContentExtractor(provider, repo)

        candidate = make_candidate(
            raw_content="content",
            source_url="https://example.com/original",
        )
        query = make_query()

        result = extractor.extract_from_candidate(query, candidate)

        # source_url should never change
        assert result.source_url == "https://example.com/original"

    def test_extraction_preserves_original_fields(self) -> None:
        ai_response = """
        {
            "summary": "New summary",
            "genres": ["漫画"],
            "tags": ["日常"]
        }
        """
        provider = MockAiProvider(response=ai_response)
        repo = MockRepository()
        extractor = MetadataContentExtractor(provider, repo)

        candidate = make_candidate(
            raw_content="content",
            title="Original Title",
            source_name="萌娘百科",
            source_type="community_database",
            verified=True,
        )
        query = make_query()

        result = extractor.extract_from_candidate(query, candidate)

        assert result.source_name == "萌娘百科"
        assert result.source_type == "community_database"
        assert result.verified is True


class TestToStringList:
    def test_empty_list(self) -> None:
        assert _to_string_list([]) == []

    def test_list_of_strings(self) -> None:
        assert _to_string_list(["a", "b", "c"]) == ["a", "b", "c"]

    def test_list_with_whitespace(self) -> None:
        assert _to_string_list([" a ", " b ", ""]) == ["a", "b"]

    def test_string_converted_to_list(self) -> None:
        assert _to_string_list("single") == ["single"]

    def test_empty_string_returns_empty(self) -> None:
        assert _to_string_list("") == []

    def test_non_string_items_converted(self) -> None:
        assert _to_string_list([1, 2, 3]) == ["1", "2", "3"]

    def test_none_returns_empty(self) -> None:
        assert _to_string_list(None) == []
