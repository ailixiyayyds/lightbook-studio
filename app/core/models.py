from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


SourceType = Literal["image_folder", "epub", "cbz", "novel_txt"]
MangaDirection = Literal["rtl", "ltr", "webtoon"]
AiSuggestionStatus = Literal["pending", "running", "completed", "failed"]


class LightBookError(Exception):
    """Base exception for user-facing LightBook Studio errors."""


class ImporterError(LightBookError):
    """Raised when a source cannot be imported."""


class ExporterError(LightBookError):
    """Raised when a CBZ cannot be exported."""


@dataclass(frozen=True)
class ComicPage:
    display_name: str
    extension: str
    source_path: Path | None = None
    archive_path: str | None = None


@dataclass
class ComicMetadata:
    series_title: str = ""
    book_title: str = ""
    volume_number: int = 1
    author: str = ""
    translator: str = ""
    summary: str = ""
    genres: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    language_iso: str = "zh"
    manga_direction: MangaDirection = "rtl"


@dataclass
class ImportResult:
    source_path: Path
    source_type: SourceType
    pages: list[ComicPage]
    cover_data: bytes
    cover_extension: str
    metadata: ComicMetadata
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ExportResult:
    cbz_path: Path
    poster_path: Path
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AiMetadataSuggestion:
    clean_title: str = ""
    original_title: str = ""
    aliases: list[str] = field(default_factory=list)
    book_title: str = ""
    volume_number: int | None = None
    authors: list[str] = field(default_factory=list)
    illustrators: list[str] = field(default_factory=list)
    translators: list[str] = field(default_factory=list)
    language_iso: str = "zh"
    summary: str = ""
    genres: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    content_warnings: list[str] = field(default_factory=list)
    manga_direction: MangaDirection | str = "rtl"
    series_status: str = ""
    confidence: float = 0.0
    field_confidence: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AiSuggestionResult:
    id: int
    book_id: int
    provider: str
    status: AiSuggestionStatus
    input_snapshot: dict[str, Any]
    raw_response: str
    parsed_json: dict[str, Any]
    confidence: float
    error_message: str
    created_at: str
    updated_at: str
