from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.utils.filename import sanitize_windows_filename, unique_path


@dataclass(frozen=True)
class PlannedOutput:
    series_dir: Path
    cbz_path: Path
    poster_path: Path


@dataclass(frozen=True)
class PlannedNovelOutput:
    series_dir: Path
    epub_path: Path


def plan_comic_output(
    output_root: Path,
    series_title: str,
    book_title: str,
    volume_number: int | None,
) -> PlannedOutput:
    safe_series_title = sanitize_windows_filename(series_title)
    series_dir = output_root / "Manga" / safe_series_title

    if volume_number is None:
        safe_book_title = sanitize_windows_filename(book_title)
        cbz_name = f"{safe_book_title}.cbz"
    else:
        cbz_name = f"{safe_series_title} v{volume_number:02d}.cbz"

    return PlannedOutput(
        series_dir=series_dir,
        cbz_path=unique_path(series_dir / cbz_name),
        poster_path=series_dir / "poster.jpg",
    )


def plan_novel_output(
    output_root: Path,
    series_title: str,
    book_title: str,
    volume_number: int | None,
) -> PlannedNovelOutput:
    safe_series_title = sanitize_windows_filename(series_title)
    series_dir = output_root / "Novel" / safe_series_title

    if volume_number is None:
        safe_book_title = sanitize_windows_filename(book_title)
        epub_name = f"{safe_book_title}.epub"
    else:
        epub_name = f"{safe_series_title} v{volume_number:02d}.epub"

    return PlannedNovelOutput(
        series_dir=series_dir,
        epub_path=unique_path(series_dir / epub_name),
    )
