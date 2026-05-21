from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import cast

from app.core.models import ComicMetadata, ExporterError, MangaDirection

logger = logging.getLogger(__name__)
from app.exporters.cbz_exporter import export_cbz
from app.importers.cbz_importer import import_cbz
from app.importers.comic_epub_importer import import_comic_epub
from app.importers.image_folder_importer import import_image_folder
from app.parsers.novel_chapter_parser import NovelChapter
from app.services.output_planner import plan_novel_output
from app.storage.database import DEFAULT_DATABASE_PATH
from app.storage.repositories import RowDict, get_book, get_work, list_novel_chapters, update_book


def export_book_from_database(
    book_id: int,
    output_root: Path,
    *,
    db_path: str | Path = DEFAULT_DATABASE_PATH,
) -> Path:
    book = get_book(book_id, db_path=db_path)
    if book is None:
        raise ExporterError(f"book 不存在：{book_id}")
    work = get_work(int(book["work_id"]), db_path=db_path)
    if work is None:
        update_book(book_id, status="failed", db_path=db_path)
        raise ExporterError(f"book {book_id} 找不到对应 work。")

    is_novel = _is_novel_book(book)
    logger.info(
        "导出开始 book_id=%s media_type=%s output_root=%s",
        book_id,
        "novel" if is_novel else "comic",
        output_root,
    )
    try:
        if is_novel:
            output_path = _export_novel_book(book, work, output_root, db_path)
        else:
            output_path = _export_manga_book(book, work, output_root)
        update_book(book_id, status="exported", db_path=db_path)
        logger.info("导出成功 book_id=%s output_path=%s", book_id, output_path)
        return output_path
    except Exception:
        logger.exception("导出失败 book_id=%s", book_id)
        update_book(book_id, status="failed", db_path=db_path)
        raise


def export_novel_preview_from_database(
    book_id: int,
    output_path: Path,
    *,
    db_path: str | Path = DEFAULT_DATABASE_PATH,
) -> Path:
    book = get_book(book_id, db_path=db_path)
    if book is None:
        raise ExporterError(f"book 不存在：{book_id}")
    if not _is_novel_book(book):
        raise ExporterError(f"book {book_id} 不是轻小说条目，无法生成 EPUB 预览。")
    work = get_work(int(book["work_id"]), db_path=db_path)
    if work is None:
        raise ExporterError(f"book {book_id} 找不到对应 work。")

    chapters = _novel_chapters_from_database(book_id, db_path=db_path)
    if not chapters:
        raise ExporterError(f"book {book_id} 没有可导出的小说章节。")

    export_novel_epub = _load_epub_exporter()
    return export_novel_epub(
        series_title=str(work.get("title") or "未命名轻小说"),
        book_title=str(book.get("title") or work.get("title") or "未命名轻小说"),
        volume_number=_optional_int(book.get("volume_number")),
        author=str(work.get("author") or ""),
        summary=str(work.get("summary") or ""),
        language_iso=str(work.get("language_iso") or "zh"),
        genres=_split_terms(str(work.get("genres") or "")),
        tags=_split_terms(str(work.get("tags") or "")),
        chapters=chapters,
        output_path=output_path,
        cover_path=_book_cover_path(book),
    )


def _is_novel_book(book: RowDict) -> bool:
    return (
        str(book.get("media_type") or "") == "novel"
        or str(book.get("export_format") or "") == "epub"
        or str(book.get("source_type") or "") == "novel_txt"
    )


def _export_novel_book(
    book: RowDict,
    work: RowDict,
    output_root: Path,
    db_path: str | Path,
) -> Path:
    chapters = _novel_chapters_from_database(int(book["id"]), db_path=db_path)
    if not chapters:
        raise ExporterError(f"book {book['id']} 没有可导出的小说章节。")

    series_title = str(work.get("title") or "未命名轻小说")
    book_title = str(book.get("title") or series_title)
    volume_number = _optional_int(book.get("volume_number"))
    planned = plan_novel_output(
        output_root,
        series_title,
        book_title,
        volume_number,
    )
    planned.series_dir.mkdir(parents=True, exist_ok=True)

    export_novel_epub = _load_epub_exporter()
    export_novel_epub(
        series_title=series_title,
        book_title=book_title,
        volume_number=volume_number,
        author=str(work.get("author") or ""),
        summary=str(work.get("summary") or ""),
        language_iso=str(work.get("language_iso") or "zh"),
        genres=_split_terms(str(work.get("genres") or "")),
        tags=_split_terms(str(work.get("tags") or "")),
        chapters=chapters,
        output_path=planned.epub_path,
        cover_path=_book_cover_path(book),
    )
    return planned.epub_path


def _export_manga_book(book: RowDict, work: RowDict, output_root: Path) -> Path:
    source_path = Path(str(book["source_path"]))
    source_type = str(book["source_type"])
    if source_type == "epub":
        import_result = import_comic_epub(source_path)
    elif source_type == "cbz":
        import_result = import_cbz(source_path)
    elif source_type == "image_folder":
        import_result = import_image_folder(source_path)
    else:
        raise ExporterError(f"不支持的漫画 source_type：{source_type}")

    metadata = ComicMetadata(
        series_title=str(work.get("title") or "Untitled"),
        book_title=str(book.get("title") or work.get("title") or "Untitled"),
        volume_number=int(book.get("volume_number") or 1),
        author=str(work.get("author") or ""),
        translator=str(book.get("translator") or ""),
        summary=str(work.get("summary") or ""),
        genres=_split_terms(str(work.get("genres") or "")),
        tags=_split_terms(str(work.get("tags") or "")),
        language_iso=str(work.get("language_iso") or "zh"),
        manga_direction=_manga_direction(str(book.get("manga_direction") or "rtl")),
    )
    cover_path = _book_cover_path(book)
    if cover_path is None:
        result = export_cbz(import_result, output_root, metadata)
    else:
        result = export_cbz(
            import_result,
            output_root,
            metadata,
            cover_override_path=cover_path,
        )
    return result.cbz_path


def _book_cover_path(book: RowDict) -> Path | None:
    cover_value = str(book.get("cover_override_path") or book.get("cover_path") or "").strip()
    return Path(cover_value) if cover_value else None


def _novel_chapters_from_database(
    book_id: int,
    *,
    db_path: str | Path = DEFAULT_DATABASE_PATH,
) -> list[NovelChapter]:
    chapters: list[NovelChapter] = []
    for fallback_index, row in enumerate(list_novel_chapters(book_id, db_path=db_path), start=1):
        chapters.append(
            NovelChapter(
                title=str(row.get("title") or "正文"),
                content=str(row.get("content") or ""),
                order_index=int(row.get("order_index") or fallback_index),
            )
        )
    return chapters


def _load_epub_exporter() -> Callable[..., Path]:
    from app.exporters.epub_exporter import export_novel_epub

    return export_novel_epub


def _split_terms(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _optional_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _manga_direction(value: str) -> MangaDirection:
    if value in {"rtl", "ltr", "webtoon"}:
        return cast(MangaDirection, value)
    return "rtl"
