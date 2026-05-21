from __future__ import annotations

import httpx

from app.search.providers.moegirl_provider import (
    MoegirlProvider,
    _build_keywords,
    _is_disambiguation,
)
from app.search.types import MetadataSearchQuery


class TestMoegirlKeywords:

    def test_uses_clean_title_first(self) -> None:
        query = MetadataSearchQuery(
            title="Long Title Vol 1",
            local_clean_title="Clean Title",
        )
        kws = _build_keywords(query)
        assert kws[0] == "Clean Title"

    def test_filters_numeric_ids(self) -> None:
        query = MetadataSearchQuery(title="3159", local_clean_title="3159")
        kws = _build_keywords(query)
        assert kws == []

    def test_includes_author_queries(self) -> None:
        query = MetadataSearchQuery(
            title="Test Work",
            local_clean_title="Test Work",
            authors=["Author"],
        )
        kws = _build_keywords(query)
        assert any("Author" in kw for kw in kws)


class TestDisambiguation:

    def test_rejects_disambiguation(self) -> None:
        assert _is_disambiguation("某作品 (消歧义)") is True
        assert _is_disambiguation("某作品消歧义") is True

    def test_accepts_normal_title(self) -> None:
        assert _is_disambiguation("轻小说标题") is False
        assert _is_disambiguation("漫画名") is False


class TestMoegirlProvider:

    def test_http_error_returns_empty(self, monkeypatch) -> None:
        from app.search.providers import moegirl_provider

        def mock_get(url, **kw):
            class R:
                status_code = 500
            return R()

        monkeypatch.setattr(moegirl_provider.httpx, "get", mock_get)
        provider = MoegirlProvider()
        query = MetadataSearchQuery(title="Test", media_type="comic")
        assert provider.search(query) == []

    def test_successful_opensearch(self, monkeypatch) -> None:
        from app.search.providers import moegirl_provider

        call_count = 0

        def mock_get(url, **kw):
            nonlocal call_count
            call_count += 1
            class R:
                status_code = 200

                @staticmethod
                def json():
                    if "opensearch" in str(kw.get("params", {}).get("action", "")):
                        return ["query", ["Test Page"], [], []]
                    return {
                        "query": {
                            "pages": {
                                "123": {
                                    "title": "Test Page",
                                    "extract": "Summary text.",
                                    "fullurl": "https://zh.moegirl.org.cn/Test_Page",
                                    "original": {"source": "https://img.example.com/cover.jpg"},
                                }
                            }
                        }
                    }

            return R()

        monkeypatch.setattr(moegirl_provider.httpx, "get", mock_get)
        provider = MoegirlProvider()
        query = MetadataSearchQuery(
            title="Test Page",
            local_clean_title="Test Page",
            media_type="comic",
        )
        result = provider.search(query)
        assert len(result) >= 1
        c = result[0]
        assert c.source_name == "萌娘百科"
        assert c.cover_url == "https://img.example.com/cover.jpg"
        assert c.source_type == "community_database"
        assert c.verified is True
