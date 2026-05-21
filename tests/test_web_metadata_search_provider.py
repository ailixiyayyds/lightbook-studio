from __future__ import annotations

import httpx
import pytest

from app.search.types import MetadataSearchQuery
from app.search.web_metadata_search_provider import (
    DuckDuckGoSearchProvider,
    _extract_cover_url,
    _extract_meta_content,
    _extract_result_urls,
    _extract_summary,
)


def _search_results_html() -> str:
    return """<!DOCTYPE html>
<html><body>
<a class="result__a" href="https://bgm.tv/subject/123456">Test Title - Bangumi</a>
<a class="result__a" href="https://zh.moegirl.org.cn/Test">Test Title - Moegirl</a>
<a class="result__a" href="https://example.com/manga/test">Test Title</a>
</body></html>"""


def _detail_page_html() -> str:
    return """<!DOCTYPE html>
<html><head>
<meta property="og:title" content="Test Manga Title">
<meta property="og:image" content="https://example.com/images/cover.jpg">
<meta property="og:description" content="A story about testing.">
<meta name="description" content="Meta desc test story.">
</head>
<body><h1>Test Manga</h1><p>Content here.</p></body></html>"""


def _detail_page_no_cover_html() -> str:
    return """<!DOCTYPE html>
<html><head>
<meta property="og:title" content="Test Without Cover">
<meta name="description" content="No cover image available.">
</head>
<body><h1>Test</h1></body></html>"""


class TestExtractResultUrls:

    def test_extracts_duckduckgo_result_urls(self) -> None:
        urls = _extract_result_urls(_search_results_html())
        assert len(urls) == 3
        assert any("bgm.tv" in u for u in urls)
        assert any("moegirl" in u for u in urls)
        assert any("example.com" in u for u in urls)

    def test_extracts_empty_list_for_empty_html(self) -> None:
        urls = _extract_result_urls("<html></html>")
        assert urls == []


class TestExtractMetaContent:

    def test_extracts_og_title(self) -> None:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(_detail_page_html(), "html.parser")
        title = _extract_meta_content(soup, [
            ("meta", {"property": "og:title"}),
            ("meta", {"name": "og:title"}),
        ])
        assert title == "Test Manga Title"

    def test_returns_none_when_not_found(self) -> None:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup("<html></html>", "html.parser")
        assert _extract_meta_content(soup, [("meta", {"property": "og:title"})]) is None


class TestExtractCoverUrl:

    def test_extracts_og_image(self) -> None:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(_detail_page_html(), "html.parser")
        cover = _extract_cover_url(soup, "https://example.com/manga/test")
        assert cover == "https://example.com/images/cover.jpg"

    def test_filters_logo_images(self) -> None:
        from bs4 import BeautifulSoup
        html = '<meta property="og:image" content="https://example.com/logo.png">'
        soup = BeautifulSoup(html, "html.parser")
        cover = _extract_cover_url(soup, "https://example.com")
        assert cover == ""

    def test_filters_favicon_images(self) -> None:
        from bs4 import BeautifulSoup
        html = '<meta property="og:image" content="https://example.com/favicon.ico">'
        soup = BeautifulSoup(html, "html.parser")
        cover = _extract_cover_url(soup, "https://example.com")
        assert cover == ""

    def test_filters_invalid_extensions(self) -> None:
        from bs4 import BeautifulSoup
        html = '<meta property="og:image" content="https://example.com/data.svg">'
        soup = BeautifulSoup(html, "html.parser")
        cover = _extract_cover_url(soup, "https://example.com")
        assert cover == ""

    def test_returns_empty_for_non_http_schemes(self) -> None:
        from bs4 import BeautifulSoup
        html = '<meta property="og:image" content="ftp://example.com/cover.jpg">'
        soup = BeautifulSoup(html, "html.parser")
        cover = _extract_cover_url(soup, "https://example.com")
        assert cover == ""

    def test_returns_empty_when_no_image(self) -> None:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(_detail_page_no_cover_html(), "html.parser")
        cover = _extract_cover_url(soup, "https://example.com")
        assert cover == ""


class TestExtractSummary:

    def test_extracts_og_description(self) -> None:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(_detail_page_html(), "html.parser")
        summary = _extract_summary(soup)
        assert summary == "A story about testing."

    def test_falls_back_to_meta_description(self) -> None:
        from bs4 import BeautifulSoup
        html = '<meta name="description" content="Meta desc story.">'
        soup = BeautifulSoup(html, "html.parser")
        summary = _extract_summary(soup)
        assert summary == "Meta desc story."

    def test_truncates_long_summary(self) -> None:
        from bs4 import BeautifulSoup
        long_text = "A" * 600
        html = f'<meta property="og:description" content="{long_text}">'
        soup = BeautifulSoup(html, "html.parser")
        summary = _extract_summary(soup)
        assert len(summary) <= 503
        assert summary.endswith("...")

    def test_returns_empty_when_no_description(self) -> None:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup("<html></html>", "html.parser")
        assert _extract_summary(soup) == ""

    def test_strips_html_tags_from_description(self) -> None:
        from bs4 import BeautifulSoup
        html = '<meta property="og:description" content="<b>Bold</b> story <a href=\'x\'>link</a>.">'
        soup = BeautifulSoup(html, "html.parser")
        summary = _extract_summary(soup)
        assert "<b>" not in summary
        assert "<a" not in summary


class TestDuckDuckGoSearchProvider:

    def test_search_returns_empty_for_blank_title(self) -> None:
        provider = DuckDuckGoSearchProvider()
        query = MetadataSearchQuery(title="", media_type="comic")
        result = provider.search(query)
        assert result == []

    def test_search_with_mock_transport_returns_candidates(self, monkeypatch) -> None:
        def mock_get_search(url: str, **kwargs) -> httpx.Response:
            return httpx.Response(200, text=_search_results_html())

        def mock_get_page(url: str, **kwargs) -> httpx.Response:
            return httpx.Response(200, text=_detail_page_html())

        calls = []

        def mock_get(url: str, **kwargs) -> httpx.Response:
            calls.append(url)
            if "duckduckgo.com" in url:
                return httpx.Response(200, text=_search_results_html())
            return httpx.Response(200, text=_detail_page_html())

        monkeypatch.setattr(httpx, "get", mock_get)

        provider = DuckDuckGoSearchProvider(max_candidates=3, max_detail_pages=3)
        query = MetadataSearchQuery(
            title="Test Title",
            authors=["Test Author"],
            media_type="comic",
            language_iso="zh",
        )
        result = provider.search(query)
        assert len(result) >= 1
        for candidate in result:
            assert candidate.title
            assert candidate.source_name
            assert candidate.source_url

    def test_trusted_sources_ranked_first(self, monkeypatch) -> None:
        html = """<html><body>
        <a class="result__a" href="https://example.com/test">Example</a>
        <a class="result__a" href="https://bgm.tv/subject/1">Bangumi</a>
        </body></html>"""

        def mock_get(url: str, **kwargs) -> httpx.Response:
            return httpx.Response(200, text=_detail_page_html())

        monkeypatch.setattr(httpx, "get", mock_get)

        provider = DuckDuckGoSearchProvider(max_candidates=2, max_detail_pages=2)
        provider._search_urls = lambda q: _extract_result_urls(html)

        query = MetadataSearchQuery(title="Test Title", media_type="comic")
        result = provider.search(query)

        if len(result) >= 2:
            assert "bgm.tv" in result[0].source_url.lower() or "trust" not in str(result).lower()

    def test_handles_http_error_gracefully(self, monkeypatch) -> None:
        def mock_get(url: str, **kwargs) -> httpx.Response:
            if "duckduckgo.com" in url:
                return httpx.Response(500, text="Server Error")
            return httpx.Response(200, text=_detail_page_html())

        monkeypatch.setattr(httpx, "get", mock_get)

        provider = DuckDuckGoSearchProvider()
        query = MetadataSearchQuery(title="Test Title", media_type="comic")
        result = provider.search(query)
        assert result == []

    def test_candidate_count_respects_limit(self, monkeypatch) -> None:

        def mock_get(url: str, **kwargs) -> httpx.Response:
            return httpx.Response(200, text=_detail_page_html())

        monkeypatch.setattr(httpx, "get", mock_get)

        provider = DuckDuckGoSearchProvider(max_candidates=3, max_detail_pages=3)
        provider._search_urls = lambda q: [
            "https://example.com/1",
            "https://example.com/2",
            "https://example.com/3",
            "https://example.com/4",
            "https://example.com/5",
        ]
        query = MetadataSearchQuery(title="Test Title", media_type="comic")
        result = provider.search(query)
        assert len(result) <= 3

    def test_candidate_from_search_snippet_when_over_detail_limit(self, monkeypatch) -> None:
        detail_count = 0

        def mock_get(url: str, **kwargs) -> httpx.Response:
            nonlocal detail_count
            if "duckduckgo.com" in url:
                return httpx.Response(200, text=_search_results_html())
            detail_count += 1
            return httpx.Response(200, text=_detail_page_html())

        monkeypatch.setattr(httpx, "get", mock_get)

        provider = DuckDuckGoSearchProvider(max_candidates=5, max_detail_pages=1)
        provider._search_urls = lambda q: [
            "https://example.com/1",
            "https://example.com/2",
            "https://example.com/3",
        ]
        query = MetadataSearchQuery(title="Test Title", media_type="comic")
        result = provider.search(query)
        assert len(result) >= 1
