from __future__ import annotations

import json

import pytest

from app.ai.mock_provider import MockAiProvider
from app.ai.provider import BaseAiProvider
from app.ai.types import AiMetadataRequest, AiMetadataResponse


def test_base_ai_provider_is_abstract() -> None:
    with pytest.raises(TypeError):
        BaseAiProvider()  # type: ignore[abstract]


def test_ai_metadata_request_defaults() -> None:
    request = AiMetadataRequest(book_id=1, media_type="comic")

    assert request.book_id == 1
    assert request.media_type == "comic"
    assert request.current_metadata == {}
    assert request.source_info == {}
    assert request.chapter_titles == []
    assert request.page_count is None
    assert request.text_sample == ""
    assert request.cover_path is None


def test_mock_ai_provider_returns_required_fields_for_comic() -> None:
    provider = MockAiProvider()
    request = AiMetadataRequest(
        book_id=10,
        media_type="comic",
        current_metadata={
            "series_title": "Raw Series",
            "book_title": "Volume 1",
            "volume_number": 1,
            "language_iso": "zh",
            "manga_direction": "rtl",
        },
        source_info={"filename": "Raw Series v01.cbz"},
        page_count=123,
        cover_path="C:/covers/raw.jpg",
    )

    response = provider.suggest_metadata(request)

    assert isinstance(response, AiMetadataResponse)
    assert response.provider == "mock"
    assert response.confidence == response.parsed["confidence"]
    assert json.loads(response.raw_text) == response.parsed
    for field_name in (
        "clean_title",
        "summary",
        "genres",
        "tags",
        "language_iso",
        "manga_direction",
        "confidence",
    ):
        assert field_name in response.parsed
    assert response.parsed["clean_title"] == "Raw Series"
    assert response.parsed["book_title"] == "Volume 1"
    assert response.parsed["volume_number"] == 1
    assert response.parsed["manga_direction"] == "rtl"
    assert "123" in response.parsed["summary"]


def test_mock_ai_provider_returns_reasonable_novel_suggestion() -> None:
    provider = MockAiProvider()
    request = AiMetadataRequest(
        book_id=20,
        media_type="novel",
        current_metadata={"title": "Novel Title", "author": "Author A"},
        source_info={"filename": "3159 gbk.txt"},
        chapter_titles=["序章", "第一章"],
        text_sample="正文样本",
    )

    response = provider.suggest_metadata(request)

    assert response.parsed["clean_title"] == "Novel Title"
    assert response.parsed["authors"] == ["Author A"]
    assert response.parsed["genres"] == ["轻小说"]
    assert "2" in response.parsed["summary"]
    assert response.parsed["notes"]
