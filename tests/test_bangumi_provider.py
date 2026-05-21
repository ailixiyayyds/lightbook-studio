from __future__ import annotations

import httpx
import pytest

from app.search.providers.bangumi_provider import BangumiProvider, _build_keywords, _parse_item
from app.search.types import MetadataSearchQuery


def _bgm_item(**overrides: object) -> dict:
    return {
        "id": 123456,
        "name": "Test Manga",
        "name_cn": "测试漫画",
        "summary": "A test manga summary.",
        "images": {
            "large": "https://bgm.tv/img/large.jpg",
            "common": "https://bgm.tv/img/common.jpg",
            "medium": "https://bgm.tv/img/medium.jpg",
        },
        **overrides,
    }


class TestBangumiParse:

    def test_parses_complete_item(self) -> None:
        c = _parse_item(_bgm_item())
        assert c is not None
        assert "Test Manga" in c.title
        assert c.cover_url == "https://bgm.tv/img/large.jpg"
        assert c.source_url == "https://bgm.tv/subject/123456"
        assert c.source_name == "Bangumi"
        assert c.source_type == "community_database"
        assert c.verified is True
        assert c.summary == "A test manga summary."

    def test_falls_back_to_common_image(self) -> None:
        item = _bgm_item()
        del item["images"]["large"]
        c = _parse_item(item)
        assert c is not None
        assert c.cover_url == "https://bgm.tv/img/common.jpg"

    def test_handles_no_images(self) -> None:
        item = _bgm_item()
        del item["images"]
        c = _parse_item(item)
        assert c is not None
        assert c.cover_url == ""

    def test_handles_no_name_cn(self) -> None:
        item = _bgm_item()
        del item["name_cn"]
        c = _parse_item(item)
        assert c is not None
        assert c.title == "Test Manga"

    def test_returns_none_for_no_id(self) -> None:
        item = _bgm_item()
        del item["id"]
        assert _parse_item(item) is None

    def test_returns_none_for_empty_name(self) -> None:
        item = _bgm_item()
        item["name"] = ""
        del item["name_cn"]
        assert _parse_item(item) is None

    def test_max_8_candidates(self) -> None:
        items = [_bgm_item(id=1000 + i, name=f"Manga {i}") for i in range(15)]
        result = [c for c in (_parse_item(it) for it in items) if c is not None]
        assert len(result) == 15


class TestBangumiSearchKeywords:

    def test_uses_clean_title_first(self) -> None:
        query = MetadataSearchQuery(
            title="Long Chinese Manga Title Vol 1",
            local_clean_title="Clean Title",
        )
        keywords = _build_keywords(query)
        assert keywords[0] == "Clean Title"

    def test_filters_numeric_ids(self) -> None:
        query = MetadataSearchQuery(
            title="3159",
            local_clean_title="3159",
            raw_filename="3159 gbk.txt",
        )
        keywords = _build_keywords(query)
        assert all(kw != "3159" for kw in keywords)

    def test_includes_author_queries(self) -> None:
        query = MetadataSearchQuery(
            title="Test Manga",
            local_clean_title="Test Manga",
            authors=["Author"],
        )
        keywords = _build_keywords(query)
        assert any("Author" in kw for kw in keywords)


class TestBangumiProvider:

    def test_http_error_returns_empty(self, monkeypatch) -> None:
        from app.search.providers import bangumi_provider

        def mock_post(url, **kw):
            class R:
                status_code = 500
            return R()

        monkeypatch.setattr(bangumi_provider.httpx, "post", mock_post)
        provider = BangumiProvider()
        query = MetadataSearchQuery(title="Test", media_type="comic")
        result = provider.search(query)
        assert result == []

    def test_successful_search(self, monkeypatch) -> None:
        from app.search.providers import bangumi_provider

        def mock_post(url, **kw):
            class R:
                status_code = 200

                @staticmethod
                def json():
                    return {"data": [_bgm_item()]}

            return R()

        monkeypatch.setattr(bangumi_provider.httpx, "post", mock_post)
        provider = BangumiProvider()
        query = MetadataSearchQuery(
            title="Test Manga",
            local_clean_title="Test Manga",
            media_type="comic",
        )
        result = provider.search(query)
        assert len(result) >= 1
        assert result[0].source_name == "Bangumi"
