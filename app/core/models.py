from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


SourceType = Literal["image_folder", "epub", "cbz", "novel_txt"]
MangaDirection = Literal["rtl", "ltr", "webtoon"]


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
