from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import cast

from app.core.models import ComicMetadata, ExporterError, MangaDirection
from app.exporters.cbz_exporter import export_cbz
from app.importers.comic_epub_importer import import_comic_epub
from app.importers.image_folder_importer import import_image_folder
from app.importers.novel_txt_importer import import_novel_txt
from app.parsers.novel_chapter_parser import NovelChapter
from app.services.output_planner import plan_novel_output
from app.storage.database import DEFAULT_DATABASE_PATH
from app.storage.repositories import RowDict, get_book, get_work, update_book


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

    try:
        if _is_novel_book(book):
            output_path = _export_novel_book(book, work, output_root)
        else:
            output_path = _export_manga_book(book, work, output_root)
        update_book(book_id, status="exported", db_path=db_path)
        return output_path
    except Exception:
        update_book(book_id, status="failed", db_path=db_path)
        raise


def _is_novel_book(book: RowDict) -> bool:
    return (
        str(book.get("media_type") or "") == "novel"
        or str(book.get("export_format") or "") == "epub"
        or str(book.get("source_type") or "") == "novel_txt"
    )


def _export_novel_book(book: RowDict, work: RowDict, output_root: Path) -> Path:
    source_path = Path(str(book["source_path"]))
    novel_result = import_novel_txt(source_path)
    chapters = _flatten_novel_chapters(novel_result.volumes)
    if not chapters:
        raise ExporterError(f"没识别到章节，无法导出 EPUB：{source_path}")
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
        author=str(work.get("author") or novel_result.author_guess or ""),
        summary=str(work.get("summary") or ""),
        language_iso=str(work.get("language_iso") or "zh"),
        genres=_split_terms(str(work.get("genres") or "")),
        tags=_split_terms(str(work.get("tags") or "")),
        chapters=chapters,
        output_path=planned.epub_path,
    )
    return planned.epub_path


def _export_manga_book(book: RowDict, work: RowDict, output_root: Path) -> Path:
    source_path = Path(str(book["source_path"]))
    source_type = str(book["source_type"])
    if source_type == "epub":
        import_result = import_comic_epub(source_path)
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
    result = export_cbz(import_result, output_root, metadata)
    return result.cbz_path


def _flatten_novel_chapters(volumes: list[object]) -> list[NovelChapter]:
    chapters: list[NovelChapter] = []
    order_index = 1
    for volume in volumes:
        volume_title = str(getattr(volume, "title", "") or "")
        for chapter in getattr(volume, "chapters", []):
            chapter_title = str(getattr(chapter, "title", "") or "正文")
            title = f"{volume_title} {chapter_title}".strip() if volume_title else chapter_title
            chapters.append(
                NovelChapter(
                    title=title,
                    content=str(getattr(chapter, "content", "") or ""),
                    order_index=order_index,
                )
            )
            order_index += 1
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
