from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict
from typing import Any, Protocol

from app.ai.context_builder import build_ai_metadata_request
from app.ai.metadata_schema import validate_ai_metadata
from app.ai.provider import BaseAiProvider
from app.core.models import AiMetadataSuggestion, LightBookError


logger = logging.getLogger(__name__)


class AiSuggestionRepository(Protocol):
    def get_book(self, book_id: int) -> dict[str, Any] | None: ...

    def get_work(self, work_id: int) -> dict[str, Any] | None: ...

    def list_novel_chapters(self, book_id: int) -> list[dict[str, Any]]: ...

    def create_ai_suggestion(
        self,
        *,
        book_id: int,
        provider: str,
        status: str = "pending",
        input_snapshot: str | dict[str, Any] = "{}",
        raw_response: str = "",
        parsed_json: str | dict[str, Any] = "{}",
        confidence: float = 0,
        error_message: str = "",
    ) -> dict[str, Any]: ...

    def get_ai_suggestion(self, ai_suggestion_id: int) -> dict[str, Any] | None: ...

    def update_work(
        self,
        work_id: int,
        *,
        title: str | None = None,
        original_title: str | None = None,
        author: str | None = None,
        summary: str | None = None,
        genres: str | None = None,
        tags: str | None = None,
        language_iso: str | None = None,
    ) -> dict[str, Any] | None: ...

    def update_book(
        self,
        book_id: int,
        *,
        title: str | None = None,
        volume_number: int | None = None,
        manga_direction: str | None = None,
    ) -> dict[str, Any] | None: ...

    def create_ai_request_log(
        self,
        *,
        book_id: int | None,
        task_id: str,
        request_type: str,
        provider: str,
        model: str = "",
        request_json: Any = "{}",
        response_text: str = "",
        parsed_json: Any = "{}",
        status: str = "",
        error_message: str = "",
        duration_ms: int = 0,
    ) -> dict[str, Any]: ...


class AiSuggestionServiceError(LightBookError):
    """Raised when AI metadata suggestions cannot be generated or applied."""


class AiSuggestionService:
    def __init__(self, repository: AiSuggestionRepository, provider: BaseAiProvider) -> None:
        self.repository = repository
        self.provider = provider

    def generate_for_book(self, book_id: int) -> AiMetadataSuggestion:
        input_snapshot: dict[str, Any] = {}
        raw_response = ""
        provider_name = getattr(self.provider, "name", self.provider.__class__.__name__)
        started = time.perf_counter()
        try:
            request = build_ai_metadata_request(book_id, self.repository)
            input_snapshot = asdict(request)
            logger.info(
                "AI suggestion request built book_id=%s provider=%s provider_class=%s "
                "media_type=%s text_sample_len=%s page_count=%s",
                book_id,
                provider_name,
                self.provider.__class__.__name__,
                request.media_type,
                len(request.text_sample),
                request.page_count,
            )
            response = self.provider.suggest_metadata(request)
            raw_response = response.raw_text
            parsed = validate_ai_metadata(response.parsed)
            parsed = _backfill_from_context(parsed, input_snapshot)
            self._create_request_log(
                book_id=book_id,
                provider=response.provider or provider_name,
                input_snapshot=input_snapshot,
                raw_response=response.raw_text,
                parsed=parsed,
                status="completed",
                error_message="",
                duration_ms=_elapsed_ms(started),
            )
            row = self.repository.create_ai_suggestion(
                book_id=book_id,
                provider=response.provider or provider_name,
                status="completed",
                input_snapshot=input_snapshot,
                raw_response=response.raw_text,
                parsed_json=parsed,
                confidence=float(parsed["confidence"]),
            )
            logger.info(
                "AI suggestion saved id=%s book_id=%s status=completed provider=%s confidence=%s",
                row.get("id"),
                book_id,
                response.provider or provider_name,
                parsed["confidence"],
            )
            return _metadata_suggestion_from_dict(parsed)
        except Exception as exc:
            self._create_request_log(
                book_id=book_id,
                provider=provider_name,
                input_snapshot=input_snapshot,
                raw_response=raw_response,
                parsed={},
                status="failed",
                error_message=str(exc),
                duration_ms=_elapsed_ms(started),
            )
            row = self.repository.create_ai_suggestion(
                book_id=book_id,
                provider=provider_name,
                status="failed",
                input_snapshot=input_snapshot,
                raw_response=raw_response,
                parsed_json={},
                confidence=0,
                error_message=str(exc),
            )
            logger.exception(
                "AI suggestion saved id=%s book_id=%s status=failed provider=%s error_message=%s",
                row.get("id"),
                book_id,
                provider_name,
                str(exc),
            )
            raise AiSuggestionServiceError(f"AI metadata suggestion failed for book {book_id}: {exc}") from exc

    def _create_request_log(
        self,
        *,
        book_id: int,
        provider: str,
        input_snapshot: dict[str, Any],
        raw_response: str,
        parsed: dict[str, Any],
        status: str,
        error_message: str,
        duration_ms: int,
    ) -> None:
        create_log = getattr(self.repository, "create_ai_request_log", None)
        if create_log is None:
            return
        try:
            create_log(
                book_id=book_id,
                task_id=f"metadata_suggestion:{book_id}",
                request_type="metadata_suggestion",
                provider=provider,
                model=_provider_model(self.provider),
                request_json=input_snapshot,
                response_text=raw_response[:20000],
                parsed_json=parsed,
                status=status,
                error_message=error_message,
                duration_ms=duration_ms,
            )
        except Exception:
            logger.exception("Failed to write AI request log book_id=%s", book_id)

    def apply_suggestion(self, book_id: int, suggestion_id: int, fields: list[str]) -> None:
        selected_fields = set(fields)
        if not selected_fields:
            return

        suggestion = self.repository.get_ai_suggestion(suggestion_id)
        if suggestion is None:
            raise AiSuggestionServiceError(f"AI suggestion not found: {suggestion_id}")
        if int(suggestion["book_id"]) != book_id:
            raise AiSuggestionServiceError(
                f"AI suggestion {suggestion_id} does not belong to book {book_id}."
            )
        if str(suggestion.get("status") or "") != "completed":
            raise AiSuggestionServiceError(f"AI suggestion {suggestion_id} is not completed.")

        book = self.repository.get_book(book_id)
        if book is None:
            raise AiSuggestionServiceError(f"Book not found: {book_id}")
        work = self.repository.get_work(int(book["work_id"]))
        if work is None:
            raise AiSuggestionServiceError(f"Work not found for book: {book_id}")

        parsed = validate_ai_metadata(_json_object(suggestion.get("parsed_json")))
        work_updates: dict[str, Any] = {}
        book_updates: dict[str, Any] = {}

        if "clean_title" in selected_fields:
            work_updates["title"] = parsed["clean_title"]
        if "original_title" in selected_fields and "original_title" in work:
            work_updates["original_title"] = parsed["original_title"]
        if "book_title" in selected_fields:
            book_updates["title"] = parsed["book_title"]
        if "volume_number" in selected_fields:
            book_updates["volume_number"] = parsed["volume_number"]
        if "authors" in selected_fields:
            work_updates["author"] = parsed["authors"][0] if parsed["authors"] else ""
        if "translators" in selected_fields and "translator" in book:
            book_updates["translator"] = parsed["translators"][0] if parsed["translators"] else ""
        if "summary" in selected_fields:
            work_updates["summary"] = parsed["summary"]
        if "genres" in selected_fields:
            work_updates["genres"] = _join_list(parsed["genres"])
        if "tags" in selected_fields:
            work_updates["tags"] = _join_list(parsed["tags"])
        if "language_iso" in selected_fields:
            work_updates["language_iso"] = parsed["language_iso"]
        if "manga_direction" in selected_fields and "manga_direction" in book:
            book_updates["manga_direction"] = parsed["manga_direction"]

        if work_updates:
            self.repository.update_work(int(work["id"]), **work_updates)
        if book_updates:
            self.repository.update_book(book_id, **book_updates)


def _metadata_suggestion_from_dict(data: dict[str, Any]) -> AiMetadataSuggestion:
    return AiMetadataSuggestion(
        clean_title=str(data["clean_title"]),
        original_title=str(data["original_title"]),
        aliases=list(data["aliases"]),
        book_title=str(data["book_title"]),
        volume_number=data["volume_number"],
        authors=list(data["authors"]),
        illustrators=list(data["illustrators"]),
        translators=list(data["translators"]),
        language_iso=str(data["language_iso"]),
        summary=str(data["summary"]),
        genres=list(data["genres"]),
        tags=list(data["tags"]),
        content_warnings=list(data["content_warnings"]),
        manga_direction=str(data["manga_direction"]),
        series_status=str(data["series_status"]),
        confidence=float(data["confidence"]),
        field_confidence=dict(data["field_confidence"]),
        notes=list(data["notes"]),
    )


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise AiSuggestionServiceError("Stored AI suggestion JSON is invalid.") from exc
        if isinstance(parsed, dict):
            return parsed
    raise AiSuggestionServiceError("Stored AI suggestion JSON must be an object.")


def _join_list(values: list[str]) -> str:
    return ", ".join(values)


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.perf_counter() - started) * 1000))


def _provider_model(provider: BaseAiProvider) -> str:
    for attr in ("model", "_model"):
        value = getattr(provider, attr, "")
        if value:
            return str(value)
    return ""


def _backfill_from_context(parsed: dict[str, Any], input_snapshot: dict[str, Any]) -> dict[str, Any]:
    """Keep known author/summary hints when the provider leaves them empty."""
    result = dict(parsed)
    current = input_snapshot.get("current_metadata")
    if not isinstance(current, dict):
        current = {}
    source_info = input_snapshot.get("source_info")
    if not isinstance(source_info, dict):
        source_info = {}
    search_candidates = source_info.get("search_candidates")
    if not isinstance(search_candidates, list):
        search_candidates = []

    if not result.get("authors"):
        current_author = str(current.get("author") or "").strip()
        if current_author:
            result["authors"] = [current_author]
        else:
            for candidate in search_candidates:
                if isinstance(candidate, dict) and candidate.get("authors"):
                    result["authors"] = _string_list(candidate.get("authors"))
                    if result["authors"]:
                        break

    summary = str(result.get("summary") or "").strip()
    if not summary or _is_low_quality_summary(summary):
        fallback_summary = ""
        for candidate in search_candidates:
            if isinstance(candidate, dict):
                candidate_summary = str(candidate.get("summary") or "").strip()
                if candidate_summary and not _is_low_quality_summary(candidate_summary):
                    fallback_summary = candidate_summary
                    break
        if fallback_summary:
            result["summary"] = fallback_summary

    return result


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if value:
        return [str(value).strip()]
    return []


def _is_low_quality_summary(summary: str) -> bool:
    text = summary.strip()
    if not text:
        return True
    banned = ("这是第", "本卷为《", "共 ", "共", "元数据建议", "metadata")
    return any(part in text for part in banned)
