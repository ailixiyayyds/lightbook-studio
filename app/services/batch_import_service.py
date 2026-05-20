from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from app.core.models import ImportResult
from app.importers.cbz_importer import import_cbz
from app.importers.comic_epub_importer import import_comic_epub
from app.importers.image_folder_importer import import_image_folder
from app.importers.novel_txt_importer import NovelImportResult, import_novel_txt
from app.storage.database import DEFAULT_DATABASE_PATH
from app.storage.repositories import (
    create_book,
    create_novel_chapter,
    create_work,
    delete_novel_chapters_by_book,
    list_works,
)
from app.utils.filename_parser import parse_comic_filename
from app.utils.filename import sanitize_windows_filename

Importer = Callable[[str | Path], ImportResult]
NovelImporter = Callable[[str | Path], NovelImportResult]


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
    cbz_importer: Importer = import_cbz,
    image_folder_importer: Importer = import_image_folder,
    novel_txt_importer: NovelImporter = import_novel_txt,
) -> BatchImportResult:
    errors: list[str] = []
    book_ids: list[int] = []
    work_cache = _load_work_cache(db_path)

    for source_path in paths:
        path = Path(source_path)
        try:
            if path.suffix.casefold() == ".txt" and not path.is_dir():
                novel_result = novel_txt_importer(path)
                book = _create_novel_book(path, novel_result, work_cache, db_path)
                _save_novel_chapters(int(book["id"]), novel_result, db_path)
            else:
                importer = _select_importer(path, epub_importer, cbz_importer, image_folder_importer)
                import_result = importer(path)
                series_title, book_title, volume_number = _resolve_titles(path, import_result)
                work = _get_or_create_work(series_title, import_result, work_cache, db_path)
                book = create_book(
                    work_id=int(work["id"]),
                    title=book_title,
                    volume_number=volume_number,
                    media_type="comic",
                    source_type=import_result.source_type,
                    source_path=str(path),
                    page_count=len(import_result.pages),
                    export_format="cbz",
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
    cbz_importer: Importer,
    image_folder_importer: Importer,
) -> Importer:
    if path.is_dir():
        return image_folder_importer
    if path.suffix.casefold() == ".epub":
        return epub_importer
    if path.suffix.casefold() == ".cbz":
        return cbz_importer
    raise ValueError("unsupported source; expected an .epub file, .cbz file, .txt file, or image folder")


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


def _create_novel_book(
    path: Path,
    novel_result: NovelImportResult,
    work_cache: dict[str, dict[str, object]],
    db_path: str | Path,
) -> dict[str, object]:
    series_title = novel_result.title_guess.strip() or "未命名轻小说"
    first_volume = novel_result.volumes[0] if novel_result.volumes else None
    book_title = (
        (first_volume.title.strip() if first_volume else "")
        or sanitize_windows_filename(path.stem)
    )
    volume_number = first_volume.volume_number if first_volume else None
    existing = work_cache.get(series_title)
    if existing is None:
        existing = create_work(
            title=series_title,
            author=novel_result.author_guess,
            language_iso="zh",
            db_path=db_path,
        )
        work_cache[series_title] = existing

    return create_book(
        work_id=int(existing["id"]),
        title=book_title,
        volume_number=volume_number,
        media_type="novel",
        source_type="novel_txt",
        source_path=str(path),
        page_count=0,
        chapter_count=novel_result.chapter_count,
        text_length=novel_result.text_length,
        export_format="epub",
        status="need_review",
        db_path=db_path,
    )


def _save_novel_chapters(
    book_id: int,
    novel_result: NovelImportResult,
    db_path: str | Path,
) -> None:
    delete_novel_chapters_by_book(book_id, db_path=db_path)
    order_index = 1
    for volume in novel_result.volumes:
        volume_title = str(getattr(volume, "title", "") or "")
        for chapter in getattr(volume, "chapters", []):
            chapter_title = str(getattr(chapter, "title", "") or "正文")
            title = f"{volume_title} {chapter_title}".strip() if volume_title else chapter_title
            create_novel_chapter(
                book_id=book_id,
                title=title,
                content=str(getattr(chapter, "content", "") or ""),
                order_index=order_index,
                db_path=db_path,
            )
            order_index += 1
