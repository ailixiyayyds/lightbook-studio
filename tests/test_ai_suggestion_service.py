from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.ai.mock_provider import MockAiProvider
from app.ai.provider import BaseAiProvider
from app.ai.suggestion_service import AiSuggestionService, AiSuggestionServiceError
from app.ai.types import AiMetadataRequest, AiMetadataResponse
from app.storage import repositories


def test_generate_for_book_saves_completed_suggestion(tmp_path: Path) -> None:
    db_path = tmp_path / "lightbook.db"
    book = _create_comic_book(db_path)
    repository = _Repository(db_path)
    service = AiSuggestionService(repository, MockAiProvider())

    suggestion = service.generate_for_book(int(book["id"]))

    latest = repositories.list_latest_ai_suggestion_by_book(int(book["id"]), db_path=db_path)
    assert latest is not None
    assert latest["status"] == "completed"
    assert latest["provider"] == "mock"
    assert latest["confidence"] == pytest.approx(0.72)
    assert suggestion.clean_title == "Original Series"
    assert suggestion.tags
    assert json.loads(str(latest["parsed_json"]))["clean_title"] == "Original Series"
    assert json.loads(str(latest["input_snapshot"]))["book_id"] == book["id"]


def test_generate_for_book_saves_failed_suggestion_when_provider_fails(tmp_path: Path) -> None:
    db_path = tmp_path / "lightbook.db"
    book = _create_comic_book(db_path)
    repository = _Repository(db_path)
    service = AiSuggestionService(repository, _FailingProvider())

    with pytest.raises(AiSuggestionServiceError, match="provider exploded"):
        service.generate_for_book(int(book["id"]))

    latest = repositories.list_latest_ai_suggestion_by_book(int(book["id"]), db_path=db_path)
    assert latest is not None
    assert latest["status"] == "failed"
    assert latest["provider"] == "failing"
    assert "provider exploded" in str(latest["error_message"])
    assert json.loads(str(latest["input_snapshot"]))["book_id"] == book["id"]


def test_apply_suggestion_only_updates_selected_fields(tmp_path: Path) -> None:
    db_path = tmp_path / "lightbook.db"
    book = _create_comic_book(db_path)
    suggestion = repositories.create_ai_suggestion(
        book_id=int(book["id"]),
        provider="mock",
        status="completed",
        parsed_json={
            "clean_title": "Clean Series",
            "book_title": "Clean Book",
            "volume_number": 2,
            "authors": ["AI Author"],
            "summary": "AI summary",
            "genres": ["Drama", "Fantasy"],
            "tags": ["Tag A", "Tag B"],
            "language_iso": "ja",
            "manga_direction": "ltr",
            "confidence": 0.9,
        },
        db_path=db_path,
    )
    repository = _Repository(db_path)
    service = AiSuggestionService(repository, MockAiProvider())

    service.apply_suggestion(
        int(book["id"]),
        int(suggestion["id"]),
        ["clean_title", "authors", "tags", "manga_direction"],
    )

    updated_book = repositories.get_book(int(book["id"]), db_path=db_path)
    updated_work = repositories.get_work(int(book["work_id"]), db_path=db_path)
    assert updated_book is not None
    assert updated_work is not None
    assert updated_work["title"] == "Clean Series"
    assert updated_work["author"] == "AI Author"
    assert updated_work["tags"] == "Tag A, Tag B"
    assert updated_work["summary"] == "Existing summary"
    assert updated_work["language_iso"] == "zh"
    assert updated_book["title"] == "Existing Book"
    assert updated_book["volume_number"] == 1
    assert updated_book["manga_direction"] == "ltr"


def test_apply_suggestion_with_no_fields_does_not_modify_database(tmp_path: Path) -> None:
    db_path = tmp_path / "lightbook.db"
    book = _create_comic_book(db_path)
    suggestion = repositories.create_ai_suggestion(
        book_id=int(book["id"]),
        provider="mock",
        status="completed",
        parsed_json={
            "clean_title": "Clean Series",
            "book_title": "Clean Book",
            "authors": ["AI Author"],
            "summary": "AI summary",
            "tags": ["Tag A"],
        },
        db_path=db_path,
    )
    repository = _Repository(db_path)
    service = AiSuggestionService(repository, MockAiProvider())

    service.apply_suggestion(int(book["id"]), int(suggestion["id"]), [])

    unchanged_book = repositories.get_book(int(book["id"]), db_path=db_path)
    unchanged_work = repositories.get_work(int(book["work_id"]), db_path=db_path)
    assert unchanged_book is not None
    assert unchanged_work is not None
    assert unchanged_work["title"] == "Original Series"
    assert unchanged_work["author"] == "Existing Author"
    assert unchanged_work["tags"] == "old-tag"
    assert unchanged_book["title"] == "Existing Book"


def test_generate_for_book_saves_complete_real_provider_shape(tmp_path: Path) -> None:
    db_path = tmp_path / "lightbook.db"
    book = _create_comic_book(db_path)
    repository = _Repository(db_path)
    service = AiSuggestionService(repository, _RichProvider())

    suggestion = service.generate_for_book(int(book["id"]))
    latest = repositories.list_latest_ai_suggestion_by_book(int(book["id"]), db_path=db_path)

    assert latest is not None
    parsed = json.loads(str(latest["parsed_json"]))
    assert latest["status"] == "completed"
    assert parsed["clean_title"] == "輕聲密語"
    assert parsed["book_title"] == "第 04 卷"
    assert parsed["authors"] == ["池田學志"]
    assert parsed["summary"] == "本卷为《輕聲密語》的第 04 卷。"
    assert parsed["genres"] == ["漫画", "百合", "校园"]
    assert parsed["tags"] == ["青春", "同学", "日常"]
    assert parsed["language_iso"] == "zh-TW"
    assert parsed["manga_direction"] == "rtl"
    assert suggestion.clean_title == "輕聲密語"


def _create_comic_book(db_path: Path) -> dict[str, Any]:
    work = repositories.create_work(
        title="Original Series",
        author="Existing Author",
        summary="Existing summary",
        genres="old-genre",
        tags="old-tag",
        language_iso="zh",
        db_path=db_path,
    )
    return repositories.create_book(
        work_id=int(work["id"]),
        title="Existing Book",
        volume_number=1,
        media_type="comic",
        source_type="cbz",
        source_path="C:/Books/Original Series v01.cbz",
        page_count=42,
        manga_direction="rtl",
        db_path=db_path,
    )


class _FailingProvider(BaseAiProvider):
    name = "failing"

    def suggest_metadata(self, request: AiMetadataRequest) -> AiMetadataResponse:
        raise RuntimeError("provider exploded")


class _RichProvider(BaseAiProvider):
    name = "openai_compatible"

    def suggest_metadata(self, request: AiMetadataRequest) -> AiMetadataResponse:
        parsed = {
            "clean_title": "輕聲密語",
            "book_title": "第 04 卷",
            "authors": ["池田學志"],
            "summary": "本卷为《輕聲密語》的第 04 卷。",
            "genres": ["漫画", "百合", "校园"],
            "tags": ["青春", "同学", "日常"],
            "language_iso": "zh-TW",
            "manga_direction": "rtl",
            "confidence": 0.86,
        }
        return AiMetadataResponse(
            raw_text=json.dumps(parsed, ensure_ascii=False),
            parsed=parsed,
            provider=self.name,
            confidence=0.86,
        )


class _Repository:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def get_book(self, book_id: int) -> dict[str, Any] | None:
        return repositories.get_book(book_id, db_path=self.db_path)

    def get_work(self, work_id: int) -> dict[str, Any] | None:
        return repositories.get_work(work_id, db_path=self.db_path)

    def list_novel_chapters(self, book_id: int) -> list[dict[str, Any]]:
        return repositories.list_novel_chapters(book_id, db_path=self.db_path)

    def create_ai_suggestion(self, **kwargs: Any) -> dict[str, Any]:
        return repositories.create_ai_suggestion(**kwargs, db_path=self.db_path)

    def get_ai_suggestion(self, ai_suggestion_id: int) -> dict[str, Any] | None:
        return repositories.get_ai_suggestion(ai_suggestion_id, db_path=self.db_path)

    def update_work(self, work_id: int, **kwargs: Any) -> dict[str, Any] | None:
        return repositories.update_work(work_id, **kwargs, db_path=self.db_path)

    def update_book(self, book_id: int, **kwargs: Any) -> dict[str, Any] | None:
        return repositories.update_book(book_id, **kwargs, db_path=self.db_path)
