from __future__ import annotations

import json

import httpx
import pytest

from app.search.providers.google_books_provider import GoogleBooksProvider, _parse_items
from app.search.providers.open_library_provider import OpenLibraryProvider, _parse_docs
from app.search.providers.other_providers import (
    AmazonJpProvider,
    GenericSearchProvider,
    ManualUrlProvider,
    NdlSearchProvider,
)
from app.search.types import MetadataSearchQuery


def _gbooks_item(**overrides: object) -> dict:
    return {
        "volumeInfo": {
            "title": "Test Book",
            "authors": ["Test Author"],
            "publisher": "Test Publisher",
            "publishedDate": "2020-01-01",
            "description": "A test description.",
            "industryIdentifiers": [
                {"type": "ISBN_13", "identifier": "9781234567890"},
            ],
            "imageLinks": {
                "thumbnail": "http://books.google.com/cover.jpg",
            },
            "infoLink": "https://books.google.com/books?id=test",
            "categories": ["Comics"],
        },
        **overrides,
    }


class TestGoogleBooksParse:

    def test_parses_full_item(self) -> None:
        result = _parse_items([_gbooks_item()])
        assert len(result) == 1
        c = result[0]
        assert c.title == "Test Book"
        assert c.authors == ["Test Author"]
        assert c.publisher == "Test Publisher"
        assert c.publication_date == "2020-01-01"
        assert c.summary == "A test description."
        assert c.isbn == "ISBN_13:9781234567890"
        assert c.cover_url == "https://books.google.com/cover.jpg"
        assert c.source_name == "Google Books"
        assert c.source_type == "library_metadata"
        assert c.verified is True
        assert c.genres == ["Comics"]

    def test_handles_missing_image_links(self) -> None:
        item = _gbooks_item()
        del item["volumeInfo"]["imageLinks"]
        result = _parse_items([item])
        assert result[0].cover_url == ""

    def test_handles_missing_description(self) -> None:
        item = _gbooks_item()
        del item["volumeInfo"]["description"]
        result = _parse_items([item])
        assert result[0].summary == ""

    def test_handles_missing_isbn(self) -> None:
        item = _gbooks_item()
        del item["volumeInfo"]["industryIdentifiers"]
        result = _parse_items([item])
        assert result[0].isbn == ""

    def test_handles_empty_title(self) -> None:
        item = _gbooks_item()
        item["volumeInfo"]["title"] = ""
        result = _parse_items([item])
        assert result == []

    def test_max_5_results(self) -> None:
        result = _parse_items([_gbooks_item() for _ in range(10)])
        assert len(result) == 5

    def test_http_error_returns_empty(self, monkeypatch) -> None:
        def mock_get(url, **kw):
            class R:
                status_code = 500
            return R()

        monkeypatch.setattr(httpx, "get", mock_get)
        provider = GoogleBooksProvider()
        query = MetadataSearchQuery(title="Test", media_type="comic")
        assert provider.search(query) == []

    def test_successful_search(self, monkeypatch) -> None:
        from app.search.providers import google_books_provider
        google_books_provider._cache.clear()

        def mock_get(url, **kw):
            class R:
                status_code = 200

                @staticmethod
                def json():
                    return {"items": [_gbooks_item()]}

            return R()

        monkeypatch.setattr(google_books_provider.httpx, "get", mock_get)
        provider = GoogleBooksProvider()
        query = MetadataSearchQuery(title="Test Book", local_clean_title="Test Book", media_type="comic")
        result = provider.search(query)
        assert len(result) >= 1
        assert any(c.title == "Test Book" for c in result)


def _ol_doc(**overrides: object) -> dict:
    return {
        "title": "Test Book",
        "author_name": ["Test Author"],
        "publisher": ["Test Publisher"],
        "first_publish_year": 2020,
        "isbn": ["9781234567890"],
        "cover_i": 12345,
        "key": "/works/OL123W",
        "subject": ["Fiction", "Comics"],
        **overrides,
    }


class TestOpenLibraryParse:

    def test_parses_full_doc(self) -> None:
        result = _parse_docs([_ol_doc()])
        assert len(result) == 1
        c = result[0]
        assert c.title == "Test Book"
        assert c.authors == ["Test Author"]
        assert c.publisher == "Test Publisher"
        assert c.publication_date == "2020"
        assert c.isbn == "9781234567890"
        assert c.cover_url == "https://covers.openlibrary.org/b/id/12345-L.jpg"
        assert c.source_url == "https://openlibrary.org/works/OL123W"
        assert c.source_type == "library_metadata"
        assert c.verified is True

    def test_handles_no_cover(self) -> None:
        doc = _ol_doc()
        del doc["cover_i"]
        result = _parse_docs([doc])
        assert result[0].cover_url == ""

    def test_handles_no_key(self) -> None:
        doc = _ol_doc()
        del doc["key"]
        result = _parse_docs([doc])
        assert result[0].source_url == ""

    def test_max_5_docs(self) -> None:
        result = _parse_docs([_ol_doc() for _ in range(10)])
        assert len(result) == 5

    def test_successful_search(self, monkeypatch) -> None:
        def mock_get(url, **kw):
            class R:
                status_code = 200

                @staticmethod
                def json():
                    return {"docs": [_ol_doc()]}

            return R()

        monkeypatch.setattr(httpx, "get", mock_get)
        provider = OpenLibraryProvider()
        query = MetadataSearchQuery(title="Test", media_type="comic")
        result = provider.search(query)
        assert len(result) == 1


class TestPlaceholderProviders:

    def test_ndl_returns_empty(self) -> None:
        provider = NdlSearchProvider()
        assert provider.search(MetadataSearchQuery(title="Test")) == []

    def test_amazon_returns_empty_when_disabled(self) -> None:
        provider = AmazonJpProvider(enabled=False)
        assert provider.search(MetadataSearchQuery(title="Test")) == []

    def test_generic_search_returns_empty_when_disabled(self) -> None:
        provider = GenericSearchProvider(enabled=False)
        assert provider.search(MetadataSearchQuery(title="Test")) == []


class TestManualUrlProvider:

    def test_creates_candidate_from_url(self) -> None:
        provider = ManualUrlProvider()
        c = provider.create_from_url("https://example.com/cover.jpg")
        assert c is not None
        assert c.cover_url == "https://example.com/cover.jpg"
        assert c.source_name == "用户手动输入"
        assert c.source_type == "manual"
        assert c.verified is True
        assert "程序未验证版权来源" in " ".join(c.notes)

    def test_rejects_non_http(self) -> None:
        provider = ManualUrlProvider()
        assert provider.create_from_url("ftp://evil.com/cover.jpg") is None
        assert provider.create_from_url("") is None

    def test_accepts_title_and_source(self) -> None:
        provider = ManualUrlProvider()
        c = provider.create_from_url(
            "https://example.com/cover.jpg",
            source_url="https://example.com/page",
            title="My Book",
        )
        assert c is not None
        assert c.title == "My Book"
        assert c.source_url == "https://example.com/page"
