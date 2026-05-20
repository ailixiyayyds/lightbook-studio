from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from app.core.models import ImportResult
from app.importers.comic_epub_importer import import_comic_epub
from app.importers.image_folder_importer import import_image_folder
from app.storage.database import DEFAULT_DATABASE_PATH
from app.storage.repositories import create_book, create_work, list_works
from app.utils.filename_parser import parse_comic_filename

Importer = Callable[[str | Path], ImportResult]


@dataclass(frozen=True)
class BatchImportResult:
    imported_count: int
    failed_count: int
    errors: list[str] = field(default_factory=list)
    book_ids: list[int] = field(default_factory=list)


def batch_import(
    paths: list[Path],
    *,
    db_path: str | Path = DEFAULT_DATABASE_PATH,
    epub_importer: Importer = import_comic_epub,
    image_folder_importer: Importer = import_image_folder,
) -> BatchImportResult:
    errors: list[str] = []
    book_ids: list[int] = []
    work_cache = _load_work_cache(db_path)

    for source_path in paths:
        path = Path(source_path)
        try:
            importer = _select_importer(path, epub_importer, image_folder_importer)
            import_result = importer(path)
            series_title, book_title, volume_number = _resolve_titles(path, import_result)
            work = _get_or_create_work(series_title, import_result, work_cache, db_path)
            book = create_book(
                work_id=int(work["id"]),
                title=book_title,
                volume_number=volume_number,
                source_type=import_result.source_type,
                source_path=str(path),
                page_count=len(import_result.pages),
                translator=import_result.metadata.translator,
                manga_direction=import_result.metadata.manga_direction,
                status="need_review",
                db_path=db_path,
            )
            book_ids.append(int(book["id"]))
        except Exception as exc:
            errors.append(f"{path}: {exc}")

    return BatchImportResult(
        imported_count=len(book_ids),
        failed_count=len(errors),
        errors=errors,
        book_ids=book_ids,
    )


def _select_importer(
    path: Path,
    epub_importer: Importer,
    image_folder_importer: Importer,
) -> Importer:
    if path.is_dir():
        return image_folder_importer
    if path.suffix.casefold() == ".epub":
        return epub_importer
    raise ValueError("unsupported source; expected an .epub file or image folder")


def _resolve_titles(path: Path, import_result: ImportResult) -> tuple[str, str, int | None]:
    parsed = parse_comic_filename(path.name)
    metadata = import_result.metadata
    series_title = (
        parsed.series_title.strip()
        or metadata.series_title.strip()
        or metadata.book_title.strip()
        or path.stem
        or "Untitled"
    )
    book_title = (
        parsed.book_title.strip()
        or metadata.book_title.strip()
        or metadata.series_title.strip()
        or series_title
    )
    return series_title, book_title, parsed.volume_number


def _load_work_cache(db_path: str | Path) -> dict[str, dict[str, object]]:
    return {str(work["title"]): work for work in list_works(db_path=db_path)}


def _get_or_create_work(
    series_title: str,
    import_result: ImportResult,
    work_cache: dict[str, dict[str, object]],
    db_path: str | Path,
) -> dict[str, object]:
    existing = work_cache.get(series_title)
    if existing is not None:
        return existing

    metadata = import_result.metadata
    work = create_work(
        title=series_title,
        author=metadata.author,
        summary=metadata.summary,
        genres=", ".join(metadata.genres),
        tags=", ".join(metadata.tags),
        language_iso=metadata.language_iso or "zh",
        db_path=db_path,
    )
    work_cache[series_title] = work
    return work
