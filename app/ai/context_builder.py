from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol
import json

from app.ai.title_cleaner import clean_release_title, infer_book_title
from app.ai.types import AiMetadataRequest
from app.core.models import LightBookError


class MetadataRepository(Protocol):
    def get_book(self, book_id: int) -> dict[str, Any] | None: ...

    def get_work(self, work_id: int) -> dict[str, Any] | None: ...

    def list_novel_chapters(self, book_id: int) -> list[dict[str, Any]]: ...

    def get_latest_metadata_search_result_by_book(self, book_id: int) -> dict[str, Any] | None: ...


class MetadataContextBuilderError(LightBookError):
    """Raised when AI metadata context cannot be built from local data."""


def build_ai_metadata_request(book_id: int, repository: MetadataRepository) -> AiMetadataRequest:
    book = repository.get_book(book_id)
    if book is None:
        raise MetadataContextBuilderError(f"book 不存在：{book_id}")

    work = repository.get_work(int(book["work_id"]))
    if work is None:
        raise MetadataContextBuilderError(f"book {book_id} 找不到对应 work。")

    media_type = _media_type(book)
    source_path = str(book.get("source_path") or "")
    source_type = str(book.get("source_type") or "")
    raw_series_title = str(work.get("title") or "")
    raw_book_title = str(book.get("title") or "")
    cover_path = _cover_path(book)
    chapter_titles: list[str] = []
    text_sample = ""

    if media_type == "novel":
        chapters = repository.list_novel_chapters(book_id)
        chapter_titles = [str(chapter.get("title") or "") for chapter in chapters[:80]]
        text_sample = _novel_text_sample(chapters)

    page_count = int(book.get("page_count") or 0) if media_type == "comic" else None

    search_candidates = _search_candidates_for_ai(book_id, repository)
    if not search_candidates:
        raw_search = book.get("search_candidates")
        if isinstance(raw_search, list):
            search_candidates = _compact_search_candidates(raw_search)
        elif isinstance(raw_search, str):
            try:
                parsed = json.loads(raw_search)
                if isinstance(parsed, list):
                    search_candidates = _compact_search_candidates(parsed)
            except json.JSONDecodeError:
                pass

    return AiMetadataRequest(
        book_id=book_id,
        media_type=media_type,
        current_metadata=_current_metadata(book, work),
        source_info={
            "source_type": source_type,
            "source_path": source_path,
            "original_filename": Path(source_path).name,
            "source_filename": Path(source_path).name,
            "raw_series_title": raw_series_title,
            "raw_book_title": raw_book_title,
            "local_clean_guess": {
                "clean_title": clean_release_title(raw_series_title or raw_book_title or Path(source_path).name),
                "book_title": infer_book_title(
                    _optional_int(book.get("volume_number")),
                    raw_book_title,
                ),
                "volume_number": _optional_int(book.get("volume_number")),
            },
            "chapter_count": int(book.get("chapter_count") or 0),
            "search_candidates": search_candidates,
        },
        chapter_titles=chapter_titles,
        page_count=page_count,
        text_sample=text_sample,
        cover_path=cover_path,
    )


def _current_metadata(book: dict[str, Any], work: dict[str, Any]) -> dict[str, Any]:
    return {
        "series_title": str(work.get("title") or ""),
        "book_title": str(book.get("title") or ""),
        "volume_number": book.get("volume_number"),
        "translator": str(book.get("translator") or ""),
        "author": str(work.get("author") or ""),
        "summary": str(work.get("summary") or ""),
        "genres": str(work.get("genres") or ""),
        "tags": str(work.get("tags") or ""),
        "language_iso": str(work.get("language_iso") or "zh"),
        "manga_direction": str(book.get("manga_direction") or "rtl"),
    }


def _media_type(book: dict[str, Any]) -> str:
    media_type = str(book.get("media_type") or "").strip()
    if media_type:
        return media_type
    if str(book.get("source_type") or "") == "novel_txt" or str(book.get("export_format") or "") == "epub":
        return "novel"
    return "comic"


def _cover_path(book: dict[str, Any]) -> str | None:
    for key in ("cover_override_path", "cover_path"):
        value = str(book.get(key) or "").strip()
        if value:
            return value
    return None


def _novel_text_sample(chapters: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    total_length = 0
    for chapter in chapters:
        content = str(chapter.get("content") or "")
        if not content:
            continue
        remaining = 5000 - total_length
        if remaining <= 0:
            break
        parts.append(content[:remaining])
        total_length += len(parts[-1])
    return "".join(parts)


def _search_candidates_for_ai(book_id: int, repository: MetadataRepository) -> list[dict[str, Any]]:
    getter = getattr(repository, "get_latest_metadata_search_result_by_book", None)
    if getter is None:
        return []
    try:
        result = getter(book_id)
    except Exception:
        return []
    if not result:
        return []
    raw_candidates = result.get("candidates_json")
    if isinstance(raw_candidates, str):
        try:
            raw_candidates = json.loads(raw_candidates)
        except json.JSONDecodeError:
            return []
    if not isinstance(raw_candidates, list):
        return []
    return _compact_search_candidates(raw_candidates)


def _compact_search_candidates(candidates: list[Any]) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        extraction = candidate.get("extraction_json")
        if not isinstance(extraction, dict):
            extraction = {}
        match = extraction.get("match_assessment")
        if isinstance(match, dict) and match.get("is_likely_same_work") is False:
            continue
        if candidate.get("extraction_status") and candidate.get("extraction_status") != "extracted":
            continue
        summary = str(
            candidate.get("summary")
            or extraction.get("summary_zh")
            or extraction.get("summary")
            or ""
        ).strip()
        compact.append(
            {
                "title": str(candidate.get("title") or extraction.get("title") or "").strip(),
                "original_title": str(
                    candidate.get("original_title") or extraction.get("original_title") or ""
                ).strip(),
                "authors": _list_value(candidate.get("authors") or extraction.get("authors")),
                "publisher": str(candidate.get("publisher") or extraction.get("publisher") or "").strip(),
                "publication_date": str(
                    candidate.get("publication_date") or extraction.get("publication_date") or ""
                ).strip(),
                "summary": summary,
                "genres": _list_value(candidate.get("genres") or extraction.get("genres")),
                "tags": _list_value(candidate.get("tags") or extraction.get("tags")),
                "source_name": str(candidate.get("source_name") or "").strip(),
                "source_url": str(candidate.get("source_url") or "").strip(),
            }
        )
        if len(compact) >= 3:
            break
    return compact


def _list_value(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if value:
        return [str(value).strip()]
    return []


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
