from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from app.ai.types import AiMetadataRequest
from app.core.models import LightBookError


class MetadataRepository(Protocol):
    def get_book(self, book_id: int) -> dict[str, Any] | None: ...

    def get_work(self, work_id: int) -> dict[str, Any] | None: ...

    def list_novel_chapters(self, book_id: int) -> list[dict[str, Any]]: ...


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
    cover_path = _cover_path(book)
    chapter_titles: list[str] = []
    text_sample = ""

    if media_type == "novel":
        chapters = repository.list_novel_chapters(book_id)
        chapter_titles = [str(chapter.get("title") or "") for chapter in chapters[:80]]
        text_sample = _novel_text_sample(chapters)

    page_count = int(book.get("page_count") or 0) if media_type == "comic" else None

    return AiMetadataRequest(
        book_id=book_id,
        media_type=media_type,
        current_metadata=_current_metadata(book, work),
        source_info={
            "source_type": source_type,
            "source_path": source_path,
            "original_filename": Path(source_path).name,
            "chapter_count": int(book.get("chapter_count") or 0),
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
