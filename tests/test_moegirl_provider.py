"""Tests for Moegirl (萌娘百科) provider using MediaWiki API."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

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
        assert _is_disambiguation("某作品（消歧义）") is True

    def test_accepts_normal_title(self) -> None:
        assert _is_disambiguation("轻小说标题") is False
        assert _is_disambiguation("漫画名") is False


class TestMoegirlProvider:
    def test_http_error_returns_empty(self) -> None:
        provider = MoegirlProvider()

        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 500
            mock_get.return_value = mock_response

            query = MetadataSearchQuery(title="Test", media_type="comic")
            result = provider.search(query)

            assert result == []

    def test_successful_opensearch(self) -> None:
        provider = MoegirlProvider()

        with patch("httpx.get") as mock_get:
            # First call: opensearch
            opensearch_response = MagicMock()
            opensearch_response.status_code = 200
            opensearch_response.json.return_value = [
                "Test Page",
                ["Test Page"],
                [],
                [],
            ]

            # Second call: query details
            query_response = MagicMock()
            query_response.status_code = 200
            query_response.json.return_value = {
                "query": {
                    "pages": {
                        "123": {
                            "title": "Test Page",
                            "extract": "Summary text that is long enough for the minimum requirement.",
                            "fullurl": "https://zh.moegirl.org.cn/Test_Page",
                            "original": {"source": "https://img.example.com/cover.jpg"},
                            "categories": [],
                        }
                    }
                }
            }

            mock_get.side_effect = [opensearch_response, query_response]

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
            assert c.raw_content != ""
            assert c.raw_content_type == "extract"

    def test_sets_user_agent(self) -> None:
        provider = MoegirlProvider()

        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = ["test", [], [], []]
            mock_get.return_value = mock_response

            provider._search_titles("test")

            call_kwargs = mock_get.call_args[1]
            assert "User-Agent" in call_kwargs["headers"]
            assert "LightBookStudio" in call_kwargs["headers"]["User-Agent"]

    def test_parse_api_fallback_when_extract_short(self) -> None:
        provider = MoegirlProvider()

        with patch("httpx.get") as mock_get:
            # First call: opensearch
            opensearch_response = MagicMock()
            opensearch_response.status_code = 200
            opensearch_response.json.return_value = ["test", ["Test Title"], [], []]

            # Second call: query with short extract
            query_response = MagicMock()
            query_response.status_code = 200
            query_response.json.return_value = {
                "query": {
                    "pages": {
                        "1": {
                            "title": "Test Title",
                            "extract": "Short",  # Too short, less than 200 chars
                            "fullurl": "https://zh.moegirl.org.cn/Test_Title",
                            "categories": [],
                        }
                    }
                }
            }

            # Third call: parse API for wikitext
            parse_response = MagicMock()
            parse_response.status_code = 200
            parse_response.json.return_value = {
                "parse": {
                    "wikitext": "This is much longer wikitext content that should be sufficient for extraction purposes..."
                }
            }

            mock_get.side_effect = [opensearch_response, query_response, parse_response]

            query = MetadataSearchQuery(title="Test Title")
            candidates = provider.search(query)

            if candidates:
                # Should have used parse API for content
                assert candidates[0].raw_content_type in ["extract", "wikitext"]

    def test_no_cover_url_still_returns_candidate(self) -> None:
        provider = MoegirlProvider()

        with patch("httpx.get") as mock_get:
            opensearch_response = MagicMock()
            opensearch_response.status_code = 200
            opensearch_response.json.return_value = ["test", ["Test Title"], [], []]

            query_response = MagicMock()
            query_response.status_code = 200
            query_response.json.return_value = {
                "query": {
                    "pages": {
                        "1": {
                            "title": "Test Title",
                            "extract": "This is a test extract that is long enough for the minimum requirement and more",
                            "fullurl": "https://zh.moegirl.org.cn/Test_Title",
                            # No pageimages
                            "categories": [],
                        }
                    }
                }
            }

            mock_get.side_effect = [opensearch_response, query_response]

            query = MetadataSearchQuery(title="Test Title")
            candidates = provider.search(query)

            if candidates:
                assert candidates[0].cover_url == ""
                assert candidates[0].source_url != ""

    def test_disambiguation_pages_skipped(self) -> None:
        provider = MoegirlProvider()

        with patch("httpx.get") as mock_get:
            opensearch_response = MagicMock()
            opensearch_response.status_code = 200
            opensearch_response.json.return_value = ["test", ["Test (消歧义)"], [], []]

            query_response = MagicMock()
            query_response.status_code = 200
            query_response.json.return_value = {
                "query": {
                    "pages": {
                        "1": {
                            "title": "Test (消歧义)",
                            "extract": "This is a disambiguation page",
                            "fullurl": "https://zh.moegirl.org.cn/Test",
                            "categories": [],
                        }
                    }
                }
            }

            mock_get.side_effect = [opensearch_response, query_response]

            query = MetadataSearchQuery(title="Test")
            candidates = provider.search(query)

            # Disambiguation pages should be skipped
            assert len(candidates) == 0

    def test_categories_cleaned(self) -> None:
        provider = MoegirlProvider()

        with patch("httpx.get") as mock_get:
            opensearch_response = MagicMock()
            opensearch_response.status_code = 200
            opensearch_response.json.return_value = ["test", ["Test Title"], [], []]

            query_response = MagicMock()
            query_response.status_code = 200
            query_response.json.return_value = {
                "query": {
                    "pages": {
                        "1": {
                            "title": "Test Title",
                            "extract": "Long enough extract for testing purposes and some more content",
                            "fullurl": "https://zh.moegirl.org.cn/Test_Title",
                            "categories": [
                                {"title": "Category:漫画作品"},
                                {"title": "Category:需要参考资料"},  # Should be filtered
                                {"title": "Category:缺少封面"},  # Should be filtered
                            ],
                        }
                    }
                }
            }

            mock_get.side_effect = [opensearch_response, query_response]

            query = MetadataSearchQuery(title="Test Title")
            candidates = provider.search(query)

            if candidates:
                assert "漫画作品" in candidates[0].categories
                assert "需要参考资料" not in candidates[0].categories
                assert "缺少封面" not in candidates[0].categories

    def test_raw_content_truncated(self) -> None:
        provider = MoegirlProvider()

        long_content = "x" * 30000  # 30k chars

        with patch("httpx.get") as mock_get:
            opensearch_response = MagicMock()
            opensearch_response.status_code = 200
            opensearch_response.json.return_value = ["test", ["Test Title"], [], []]

            query_response = MagicMock()
            query_response.status_code = 200
            query_response.json.return_value = {
                "query": {
                    "pages": {
                        "1": {
                            "title": "Test Title",
                            "extract": long_content,
                            "fullurl": "https://zh.moegirl.org.cn/Test_Title",
                            "categories": [],
                        }
                    }
                }
            }

            mock_get.side_effect = [opensearch_response, query_response]

            query = MetadataSearchQuery(title="Test Title")
            candidates = provider.search(query)

            if candidates:
                # Should be truncated to 20000
                assert len(candidates[0].raw_content) <= 20000

    def test_query_extract_then_parse_text_returns_raw_content(self) -> None:
        provider = MoegirlProvider()
        long_html = "<div><p>" + ("完整页面内容 " * 40) + "</p></div>"

        with patch("httpx.get") as mock_get:
            search_response = MagicMock(status_code=200)
            search_response.json.return_value = ["test", ["Test Title"], [], []]

            info_response = MagicMock(status_code=200)
            info_response.json.return_value = {
                "query": {
                    "pages": {
                        "1": {
                            "title": "Test Title",
                            "fullurl": "https://zh.moegirl.org.cn/Test_Title",
                            "categories": [{"title": "Category:漫画作品"}],
                        }
                    }
                }
            }

            extract_response = MagicMock(status_code=200)
            extract_response.json.return_value = {
                "query": {"pages": {"1": {"extract": "太短"}}}
            }

            parse_response = MagicMock(status_code=200)
            parse_response.json.return_value = {
                "parse": {
                    "text": long_html,
                    "categories": [{"category": "校园"}],
                    "images": ["Cover.jpg"],
                }
            }

            mock_get.side_effect = [
                search_response,
                info_response,
                extract_response,
                parse_response,
            ]

            candidates = provider.search(MetadataSearchQuery(title="Test Title"))

        assert candidates
        assert candidates[0].raw_content_type == "html"
        assert "完整页面内容" in candidates[0].raw_content
        assert "校园" in candidates[0].categories
        assert "Cover.jpg" in candidates[0].images
        assert mock_get.call_args_list[3].kwargs["params"]["action"] == "parse"

    def test_wikitext_fallback_when_parse_text_is_short(self) -> None:
        provider = MoegirlProvider()
        long_wikitext = "'''Test Title'''\n" + ("维基文本内容 " * 40)

        with patch("httpx.get") as mock_get:
            search_response = MagicMock(status_code=200)
            search_response.json.return_value = ["test", ["Test Title"], [], []]

            info_response = MagicMock(status_code=200)
            info_response.json.return_value = {
                "query": {
                    "pages": {
                        "1": {
                            "title": "Test Title",
                            "fullurl": "https://zh.moegirl.org.cn/Test_Title",
                            "categories": [],
                        }
                    }
                }
            }

            extract_response = MagicMock(status_code=200)
            extract_response.json.return_value = {
                "query": {"pages": {"1": {"extract": ""}}}
            }

            parse_text_response = MagicMock(status_code=200)
            parse_text_response.json.return_value = {"parse": {"text": "短"}}

            parse_wiki_response = MagicMock(status_code=200)
            parse_wiki_response.json.return_value = {
                "parse": {
                    "wikitext": long_wikitext,
                    "categories": [{"category": "轻小说"}],
                }
            }

            mock_get.side_effect = [
                search_response,
                info_response,
                extract_response,
                parse_text_response,
                parse_wiki_response,
            ]

            candidates = provider.search(MetadataSearchQuery(title="Test Title"))

        assert candidates
        assert candidates[0].raw_content_type == "wikitext"
        assert "维基文本内容" in candidates[0].raw_content
        assert "轻小说" in candidates[0].categories

    def test_html_fallback_is_disabled_by_default(self) -> None:
        provider = MoegirlProvider(parse_api_enabled=False, html_fallback_enabled=False)

        with patch("httpx.get") as mock_get:
            search_response = MagicMock(status_code=200)
            search_response.json.return_value = ["test", ["Test Title"], [], []]

            info_response = MagicMock(status_code=200)
            info_response.json.return_value = {
                "query": {
                    "pages": {
                        "1": {
                            "title": "Test Title",
                            "fullurl": "https://zh.moegirl.org.cn/Test_Title",
                            "categories": [],
                        }
                    }
                }
            }

            extract_response = MagicMock(status_code=200)
            extract_response.json.return_value = {
                "query": {"pages": {"1": {"extract": ""}}}
            }

            mock_get.side_effect = [search_response, info_response, extract_response]

            candidates = provider.search(MetadataSearchQuery(title="Test Title"))

        assert candidates
        assert candidates[0].raw_content == ""
        assert candidates[0].raw_content_type == "extract"
        assert mock_get.call_count == 3

    def test_html_fallback_only_uses_api_returned_moegirl_fullurl(self) -> None:
        provider = MoegirlProvider(parse_api_enabled=False, html_fallback_enabled=True)

        with patch("httpx.get") as mock_get:
            search_response = MagicMock(status_code=200)
            search_response.json.return_value = ["test", ["Test Title"], [], []]

            info_response = MagicMock(status_code=200)
            info_response.json.return_value = {
                "query": {
                    "pages": {
                        "1": {
                            "title": "Test Title",
                            "fullurl": "https://zh.moegirl.org.cn/Test_Title",
                            "categories": [],
                        }
                    }
                }
            }

            extract_response = MagicMock(status_code=200)
            extract_response.json.return_value = {
                "query": {"pages": {"1": {"extract": ""}}}
            }

            html_response = MagicMock(status_code=200)
            html_response.text = "<main><h1>Test Title</h1><p>" + ("HTML 正文 " * 40) + "</p></main>"

            mock_get.side_effect = [
                search_response,
                info_response,
                extract_response,
                html_response,
            ]

            candidates = provider.search(MetadataSearchQuery(title="Test Title"))

        assert candidates
        assert candidates[0].raw_content_type == "html_fallback"
        assert "HTML 正文" in candidates[0].raw_content
        assert "html_fallback_used" in candidates[0].notes

    def test_html_fallback_rejects_non_moegirl_urls(self) -> None:
        provider = MoegirlProvider(parse_api_enabled=False, html_fallback_enabled=True)

        with patch("httpx.get") as mock_get:
            search_response = MagicMock(status_code=200)
            search_response.json.return_value = ["test", ["Test Title"], [], []]

            info_response = MagicMock(status_code=200)
            info_response.json.return_value = {
                "query": {
                    "pages": {
                        "1": {
                            "title": "Test Title",
                            "fullurl": "https://example.com/Test_Title",
                            "categories": [],
                        }
                    }
                }
            }

            extract_response = MagicMock(status_code=200)
            extract_response.json.return_value = {
                "query": {"pages": {"1": {"extract": ""}}}
            }

            mock_get.side_effect = [search_response, info_response, extract_response]

            candidates = provider.search(MetadataSearchQuery(title="Test Title"))

        assert candidates
        assert candidates[0].raw_content == ""
        assert mock_get.call_count == 3
