from __future__ import annotations

import json

import httpx
import pytest

from app.ai.config import AiProviderConfig
from app.search.ai_search_provider import (
    AiMetadataSearchProvider,
    AiSearchProviderError,
    _build_user_message,
    _extract_json,
    _is_boilerplate,
    _parse_candidates,
)
from app.search.types import MetadataSearchCandidate, MetadataSearchQuery


def _candidates_response(candidates: list[dict]) -> str:
    return json.dumps({"candidates": candidates}, ensure_ascii=False)


class TestParseCandidates:

    def test_parses_valid_candidates(self) -> None:
        resp = _candidates_response([
            {
                "title": "Test Manga",
                "authors": ["Author One"],
                "summary": "A great story about testing.",
                "cover_url": "https://example.com/cover.jpg",
                "source_name": "Bangumi",
                "source_url": "https://bgm.tv/subject/123",
                "tags": ["comedy", "school"],
                "genres": ["漫画", "校园"],
            }
        ])
        result = _parse_candidates(resp)
        assert len(result) == 1
        c = result[0]
        assert c.title == "Test Manga"
        assert c.authors == ["Author One"]
        assert c.summary == "A great story about testing."
        assert c.cover_url == "https://example.com/cover.jpg"
        assert c.source_name == "Bangumi"
        assert c.tags == ["comedy", "school"]
        assert c.genres == ["漫画", "校园"]

    def test_parses_multiple_candidates(self) -> None:
        resp = _candidates_response([
            {"title": f"Manga {i}", "source_name": f"Source {i}"}
            for i in range(5)
        ])
        result = _parse_candidates(resp)
        assert len(result) == 5

    def test_filters_empty_titles(self) -> None:
        resp = _candidates_response([
            {"title": "", "source_name": "No title"},
            {"title": "Valid", "source_name": "Has title"},
            {"title": "   ", "source_name": "Whitespace only"},
        ])
        result = _parse_candidates(resp)
        assert len(result) == 1
        assert result[0].title == "Valid"

    def test_returns_empty_for_empty_json(self) -> None:
        assert _parse_candidates("") == []
        assert _parse_candidates("not json") == []

    def test_returns_empty_when_candidates_not_list(self) -> None:
        assert _parse_candidates('{"candidates": "not a list"}') == []

    def test_handles_missing_fields_gracefully(self) -> None:
        resp = _candidates_response([{"title": "Minimal"}])
        result = _parse_candidates(resp)
        assert len(result) == 1
        c = result[0]
        assert c.title == "Minimal"
        assert c.authors == []
        assert c.summary == ""
        assert c.cover_url == ""
        assert c.source_name == "AI 搜索"

    def test_filters_non_http_cover_urls(self) -> None:
        resp = _candidates_response([
            {"title": "Test", "cover_url": "ftp://evil.com/cover.jpg"}
        ])
        result = _parse_candidates(resp)
        assert result[0].cover_url == ""

    def test_keeps_valid_cover_urls(self) -> None:
        resp = _candidates_response([
            {"title": "Test", "cover_url": "https://example.com/cover.jpg"}
        ])
        result = _parse_candidates(resp)
        assert result[0].cover_url == "https://example.com/cover.jpg"

    def test_max_6_candidates(self) -> None:
        resp = _candidates_response([
            {"title": f"Manga {i}"} for i in range(10)
        ])
        result = _parse_candidates(resp)
        assert len(result) == 6


class TestBoilerplateFilter:

    def test_rejects_volume_ref_summary(self) -> None:
        resp = _candidates_response([
            {"title": "Test", "summary": "这是第 3 卷，讲述了..."}
        ])
        result = _parse_candidates(resp)
        assert result[0].summary == ""

    def test_rejects_page_count_summary(self) -> None:
        resp = _candidates_response([
            {"title": "Test", "summary": "共 280 页，全彩漫画。"}
        ])
        result = _parse_candidates(resp)
        assert result[0].summary == ""

    def test_keeps_real_summary(self) -> None:
        resp = _candidates_response([
            {
                "title": "Test",
                "summary": "高中生小明在转学后发现自己拥有超能力，从此开启了不平凡的校园生活。"
            }
        ])
        result = _parse_candidates(resp)
        assert len(result[0].summary) > 10

    def test_keeps_english_summary(self) -> None:
        resp = _candidates_response([
            {"title": "Test", "summary": "A high school student discovers she has magical powers."}
        ])
        result = _parse_candidates(resp)
        assert result[0].summary == "A high school student discovers she has magical powers."


class TestBuildUserMessage:

    def test_includes_title_and_type(self) -> None:
        query = MetadataSearchQuery(title="Test", media_type="comic")
        msg = _build_user_message(query)
        assert "Test" in msg
        assert "comic" in msg

    def test_includes_authors(self) -> None:
        query = MetadataSearchQuery(title="Test", authors=["Author A", "Author B"], media_type="comic")
        msg = _build_user_message(query)
        assert "Author A" in msg
        assert "Author B" in msg

    def test_includes_original_title(self) -> None:
        query = MetadataSearchQuery(title="Test", original_title="Original", media_type="comic")
        msg = _build_user_message(query)
        assert "Original" in msg


class TestExtractJson:

    def test_extracts_plain_json(self) -> None:
        assert _extract_json('{"key": "value"}') == {"key": "value"}

    def test_extracts_json_inside_text(self) -> None:
        result = _extract_json('some text {"key": "value"} more text')
        assert result == {"key": "value"}

    def test_returns_empty_for_invalid(self) -> None:
        assert _extract_json("not json at all") == {}

    def test_returns_empty_for_empty_string(self) -> None:
        assert _extract_json("") == {}


class TestAiMetadataSearchProvider:

    def test_search_returns_empty_for_blank_title(self) -> None:
        config = AiProviderConfig()
        provider = AiMetadataSearchProvider(config)
        query = MetadataSearchQuery(title="", media_type="comic")
        assert provider.search(query) == []

    def test_search_raises_without_api_key(self) -> None:
        config = AiProviderConfig(api_key_env="NONEXISTENT_KEY_FOR_TEST")
        provider = AiMetadataSearchProvider(config)
        query = MetadataSearchQuery(title="Test", media_type="comic")
        with pytest.raises(AiSearchProviderError, match="API Key"):
            provider.search(query)

    def test_search_with_mock_http(self, monkeypatch) -> None:
        import json as _json

        response_body = {
            "choices": [{
                "message": {
                    "content": _json.dumps({
                        "candidates": [{
                            "title": "Mock Result",
                            "authors": ["Mock Author"],
                            "summary": "A mock story.",
                            "source_name": "MockSource",
                            "source_url": "https://mock.example.com",
                            "cover_url": "",
                            "tags": ["mock"],
                            "genres": ["漫画"],
                        }]
                    })
                }
            }]
        }

        class MockResponse:
            status_code = 200
            text = _json.dumps(response_body)

            @staticmethod
            def json():
                return response_body

        monkeypatch.setattr(httpx, "post", lambda *a, **kw: MockResponse())

        config = AiProviderConfig(api_key_env="MOCK_KEY")
        monkeypatch.setenv("MOCK_KEY", "sk-mock-key-for-testing-12345")

        provider = AiMetadataSearchProvider(config)
        query = MetadataSearchQuery(title="Test Manga", media_type="comic")
        result = provider.search(query)

        assert len(result) >= 1
        assert result[0].title == "Mock Result"
        assert result[0].authors == ["Mock Author"]
        assert result[0].genres == ["漫画"]
