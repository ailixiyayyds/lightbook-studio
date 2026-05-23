"""Tests for Bangumi provider using API v0."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.search.providers.bangumi_provider import (
    BangumiProvider,
    _build_keywords,
    _extract_first_string,
    _extract_strings,
)
from app.search.types import MetadataSearchQuery


def _bgm_search_item(**overrides: object) -> dict:
    """Create a mock search item."""
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


def _bgm_subject_detail(**overrides: object) -> dict:
    """Create a mock subject detail response."""
    return {
        "id": 123456,
        "name": "Test Manga",
        "name_cn": "测试漫画",
        "summary": "A detailed manga summary about the story and characters.",
        "images": {
            "large": "https://bgm.tv/img/large.jpg",
        },
        "tags": [
            {"name": "恋爱", "count": 100},
            {"name": "校园", "count": 80},
        ],
        "infobox": [
            {"key": "作者", "value": "Test Author"},
            {"key": "出版社", "value": "Test Publisher"},
            {"key": "发售日", "value": "2023-01-01"},
        ],
        **overrides,
    }


class TestBangumiProvider:
    def test_http_error_returns_empty(self) -> None:
        provider = BangumiProvider()

        with patch("httpx.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 500
            mock_post.return_value = mock_response

            query = MetadataSearchQuery(title="Test", media_type="comic")
            result = provider.search(query)

            assert result == []

    def test_successful_search(self) -> None:
        provider = BangumiProvider()

        with patch("httpx.post") as mock_post, patch("httpx.get") as mock_get:
            # Mock search response
            search_response = MagicMock()
            search_response.status_code = 200
            search_response.json.return_value = {"data": [_bgm_search_item()]}
            mock_post.return_value = search_response

            # Mock detail response
            detail_response = MagicMock()
            detail_response.status_code = 200
            detail_response.json.return_value = _bgm_subject_detail()
            mock_get.return_value = detail_response

            query = MetadataSearchQuery(
                title="Test Manga",
                local_clean_title="Test Manga",
                media_type="comic",
            )
            result = provider.search(query)

            assert len(result) >= 1
            assert result[0].source_name == "Bangumi"
            assert result[0].source_type == "community_database"
            assert result[0].verified is True
            assert result[0].raw_content != ""
            assert result[0].raw_content_type == "api_json"

    def test_subject_detail_provides_authors(self) -> None:
        provider = BangumiProvider()

        with patch("httpx.post") as mock_post, patch("httpx.get") as mock_get:
            search_response = MagicMock()
            search_response.status_code = 200
            search_response.json.return_value = {"data": [_bgm_search_item()]}
            mock_post.return_value = search_response

            detail_response = MagicMock()
            detail_response.status_code = 200
            detail_response.json.return_value = _bgm_subject_detail()
            mock_get.return_value = detail_response

            query = MetadataSearchQuery(title="Test Manga")
            result = provider.search(query)

            if result:
                assert "Test Author" in result[0].authors

    def test_subject_detail_provides_tags(self) -> None:
        provider = BangumiProvider()

        with patch("httpx.post") as mock_post, patch("httpx.get") as mock_get:
            search_response = MagicMock()
            search_response.status_code = 200
            search_response.json.return_value = {"data": [_bgm_search_item()]}
            mock_post.return_value = search_response

            detail_response = MagicMock()
            detail_response.status_code = 200
            detail_response.json.return_value = _bgm_subject_detail()
            mock_get.return_value = detail_response

            query = MetadataSearchQuery(title="Test Manga")
            result = provider.search(query)

            if result:
                assert "恋爱" in result[0].tags
                assert "校园" in result[0].tags

    def test_detail_failure_falls_back_to_search_item(self) -> None:
        provider = BangumiProvider()

        with patch("httpx.post") as mock_post, patch("httpx.get") as mock_get:
            # Mock search response
            search_response = MagicMock()
            search_response.status_code = 200
            search_response.json.return_value = {"data": [_bgm_search_item()]}
            mock_post.return_value = search_response

            # Mock detail response failure
            detail_response = MagicMock()
            detail_response.status_code = 500
            mock_get.return_value = detail_response

            query = MetadataSearchQuery(title="Test Manga")
            result = provider.search(query)

            # Should still return candidate from search item
            assert len(result) >= 1
            assert result[0].source_name == "Bangumi"

    def test_cover_url_from_images(self) -> None:
        provider = BangumiProvider()

        with patch("httpx.post") as mock_post, patch("httpx.get") as mock_get:
            search_response = MagicMock()
            search_response.status_code = 200
            search_response.json.return_value = {"data": [_bgm_search_item()]}
            mock_post.return_value = search_response

            detail_response = MagicMock()
            detail_response.status_code = 200
            detail_response.json.return_value = _bgm_subject_detail()
            mock_get.return_value = detail_response

            query = MetadataSearchQuery(title="Test Manga")
            result = provider.search(query)

            if result:
                assert result[0].cover_url == "https://bgm.tv/img/large.jpg"

    def test_no_cover_url_if_no_images(self) -> None:
        provider = BangumiProvider()

        with patch("httpx.post") as mock_post, patch("httpx.get") as mock_get:
            search_response = MagicMock()
            search_response.status_code = 200
            search_response.json.return_value = {
                "data": [_bgm_search_item(images={})]
            }
            mock_post.return_value = search_response

            detail_response = MagicMock()
            detail_response.status_code = 200
            detail_response.json.return_value = _bgm_subject_detail(images={})
            mock_get.return_value = detail_response

            query = MetadataSearchQuery(title="Test Manga")
            result = provider.search(query)

            if result:
                assert result[0].cover_url == ""


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


class TestExtractStrings:
    def test_string_value(self) -> None:
        assert _extract_strings("Test Author") == ["Test Author"]

    def test_list_of_strings(self) -> None:
        assert _extract_strings(["Author 1", "Author 2"]) == ["Author 1", "Author 2"]

    def test_list_of_dicts(self) -> None:
        assert _extract_strings([{"v": "Author 1"}, {"v": "Author 2"}]) == [
            "Author 1",
            "Author 2",
        ]

    def test_empty_string(self) -> None:
        assert _extract_strings("") == []

    def test_none(self) -> None:
        assert _extract_strings(None) == []


class TestExtractFirstString:
    def test_returns_first_string(self) -> None:
        assert _extract_first_string(["First", "Second"]) == "First"

    def test_returns_empty_for_empty_list(self) -> None:
        assert _extract_first_string([]) == ""

    def test_returns_string_directly(self) -> None:
        assert _extract_first_string("Direct") == "Direct"
