from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.ai.provider import BaseAiProvider
from app.ai.suggestion_service import AiSuggestionService, AiSuggestionServiceError
from app.ai.types import AiMetadataRequest, AiMetadataResponse
from app.storage import repositories


def test_metadata_suggestion_success_writes_ai_request_log(tmp_path: Path) -> None:
    db_path = tmp_path / "lightbook.db"
    book = _book(db_path)
    service = AiSuggestionService(_Repository(db_path), _SuccessProvider())

    service.generate_for_book(int(book["id"]))

    logs = repositories.list_ai_request_logs_by_book(int(book["id"]), db_path=db_path)
    assert len(logs) == 1
    log = logs[0]
    assert log["request_type"] == "metadata_suggestion"
    assert log["status"] == "completed"
    assert log["provider"] == "openai_compatible"
    assert log["model"] == "test-model"
    assert "secret" not in str(log["request_json"]).casefold()
    assert json.loads(str(log["parsed_json"]))["clean_title"] == "Clean"


def test_metadata_suggestion_failure_writes_ai_request_log(tmp_path: Path) -> None:
    db_path = tmp_path / "lightbook.db"
    book = _book(db_path)
    service = AiSuggestionService(_Repository(db_path), _FailingProvider())

    with pytest.raises(AiSuggestionServiceError):
        service.generate_for_book(int(book["id"]))

    logs = repositories.list_ai_request_logs_by_book(int(book["id"]), db_path=db_path)
    assert len(logs) == 1
    assert logs[0]["status"] == "failed"
    assert "boom" in str(logs[0]["error_message"])


def test_create_ai_request_log_truncates_response(tmp_path: Path) -> None:
    db_path = tmp_path / "lightbook.db"
    row = repositories.create_ai_request_log(
        book_id=None,
        task_id="t",
        request_type="test_connection",
        provider="p",
        response_text="x" * 21000,
        status="completed",
        db_path=db_path,
    )
    assert len(str(row["response_text"])) == 20000


def _book(db_path: Path) -> dict[str, Any]:
    work = repositories.create_work(title="Series", db_path=db_path)
    return repositories.create_book(
        work_id=int(work["id"]),
        title="Book",
        source_type="cbz",
        source_path="Book.cbz",
        db_path=db_path,
    )


class _SuccessProvider(BaseAiProvider):
    name = "openai_compatible"
    model = "test-model"

    def suggest_metadata(self, request: AiMetadataRequest) -> AiMetadataResponse:
        parsed = {
            "clean_title": "Clean",
            "book_title": "Book",
            "summary": "Summary",
            "genres": ["漫画"],
            "tags": ["测试"],
            "language_iso": "zh",
            "manga_direction": "rtl",
            "confidence": 0.8,
        }
        return AiMetadataResponse(
            raw_text=json.dumps(parsed, ensure_ascii=False),
            parsed=parsed,
            provider=self.name,
            confidence=0.8,
        )


class _FailingProvider(BaseAiProvider):
    name = "openai_compatible"
    model = "test-model"

    def suggest_metadata(self, request: AiMetadataRequest) -> AiMetadataResponse:
        raise RuntimeError("boom")


def test_metadata_content_extraction_writes_ai_request_log(tmp_path: Path) -> None:
    db_path = tmp_path / "lightbook.db"
    from app.search.content_extractor import MetadataContentExtractor
    from app.search.types import MetadataSearchCandidate, MetadataSearchQuery

    class _ExtractionProvider:
        name = "test"
        model = "test-model"

        def extract_from_content(self, system_prompt: str, user_content: str) -> str:
            return json.dumps({
                "title": "Test",
                "summary": "A test summary",
                "genres": ["漫画"],
                "tags": ["测试"],
                "match_assessment": {"is_likely_same_work": True, "reason": "title match"},
            })

    repo = _Repository(db_path)
    extractor = MetadataContentExtractor(_ExtractionProvider(), repo)
    candidate = MetadataSearchCandidate(
        title="Test",
        raw_content="Some page content",
        raw_content_type="extract",
    )
    query = MetadataSearchQuery(title="Test")
    extractor.extract_from_candidate(query, candidate, book_id=42)

    logs = repositories.list_ai_request_logs_by_book(42, db_path=db_path)
    assert len(logs) == 1
    log = logs[0]
    assert log["request_type"] == "metadata_content_extraction"
    assert log["status"] == "completed"
    assert log["provider"] == "test"


def test_metadata_content_extraction_failure_writes_ai_request_log(tmp_path: Path) -> None:
    db_path = tmp_path / "lightbook.db"
    from app.search.content_extractor import MetadataContentExtractor
    from app.search.types import MetadataSearchCandidate, MetadataSearchQuery

    class _FailingExtractionProvider:
        name = "test"
        model = "test-model"

        def extract_from_content(self, system_prompt: str, user_content: str) -> str:
            return "not valid json at all"

    repo = _Repository(db_path)
    extractor = MetadataContentExtractor(_FailingExtractionProvider(), repo)
    candidate = MetadataSearchCandidate(
        title="Test",
        raw_content="Some page content",
        raw_content_type="extract",
    )
    query = MetadataSearchQuery(title="Test")
    extractor.extract_from_candidate(query, candidate, book_id=99)

    logs = repositories.list_ai_request_logs_by_book(99, db_path=db_path)
    assert len(logs) == 1
    log = logs[0]
    assert log["request_type"] == "metadata_content_extraction"
    assert log["status"] == "failed"


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

    def create_ai_request_log(self, **kwargs: Any) -> dict[str, Any]:
        return repositories.create_ai_request_log(**kwargs, db_path=self.db_path)

    def update_work(self, work_id: int, **kwargs: Any) -> dict[str, Any] | None:
        return repositories.update_work(work_id, **kwargs, db_path=self.db_path)

    def update_book(self, book_id: int, **kwargs: Any) -> dict[str, Any] | None:
        return repositories.update_book(book_id, **kwargs, db_path=self.db_path)
