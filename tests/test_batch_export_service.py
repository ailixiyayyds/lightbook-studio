from __future__ import annotations

from pathlib import Path

import pytest

from app.core.models import ComicMetadata, ComicPage, ExportResult, ExporterError, ImportResult
from app.services import batch_export_service
from app.services.batch_export_service import export_book_from_database, export_novel_preview_from_database
from app.storage.repositories import (
    create_book,
    create_novel_chapter,
    create_work,
    get_book,
    update_novel_chapter_title,
)


def test_export_book_from_database_exports_novel_epub_from_saved_chapters(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "lightbook.db"
    work = create_work(
        title="Novel:Series",
        author="Author",
        summary="Summary",
        genres="Fantasy",
        tags="Tag",
        language_iso="zh",
        db_path=db_path,
    )
    book = create_book(
        work_id=int(work["id"]),
        title="第一卷",
        volume_number=1,
        media_type="novel",
        source_type="novel_txt",
        source_path=str(tmp_path / "source.txt"),
        chapter_count=1,
        text_length=20,
        export_format="epub",
        status="ready",
        db_path=db_path,
    )
    create_novel_chapter(
        book_id=int(book["id"]),
        title="第一卷 序章",
        content="正文",
        order_index=1,
        db_path=db_path,
    )
    exported: dict[str, object] = {}

    def fake_export_novel_epub(**kwargs):
        exported.update(kwargs)
        output_path = kwargs["output_path"]
        output_path.write_bytes(b"epub")
        return output_path

    monkeypatch.setattr(batch_export_service, "_load_epub_exporter", lambda: fake_export_novel_epub)

    output_path = export_book_from_database(int(book["id"]), tmp_path / "out", db_path=db_path)

    assert output_path == tmp_path / "out" / "Novel" / "Novel_Series" / "Novel_Series v01.epub"
    assert output_path.exists()
    assert exported["series_title"] == "Novel:Series"
    assert exported["book_title"] == "第一卷"
    assert exported["volume_number"] == 1
    assert [chapter.title for chapter in exported["chapters"]] == ["第一卷 序章"]
    assert get_book(int(book["id"]), db_path=db_path)["status"] == "exported"  # type: ignore[index]


def test_export_book_from_database_uses_edited_novel_chapter_title(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "lightbook.db"
    work = create_work(title="Novel Series", db_path=db_path)
    book = create_book(
        work_id=int(work["id"]),
        title="Volume 1",
        volume_number=1,
        media_type="novel",
        source_type="novel_txt",
        source_path=str(tmp_path / "source.txt"),
        export_format="epub",
        status="ready",
        db_path=db_path,
    )
    chapter = create_novel_chapter(
        book_id=int(book["id"]),
        title="Original Title",
        content="Chapter body",
        order_index=1,
        db_path=db_path,
    )
    update_novel_chapter_title(int(chapter["id"]), "Edited Title", db_path=db_path)
    exported: dict[str, object] = {}

    def fake_export_novel_epub(**kwargs):
        exported.update(kwargs)
        output_path = kwargs["output_path"]
        output_path.write_bytes(b"epub")
        return output_path

    monkeypatch.setattr(batch_export_service, "_load_epub_exporter", lambda: fake_export_novel_epub)

    export_book_from_database(int(book["id"]), tmp_path / "out", db_path=db_path)

    assert [chapter.title for chapter in exported["chapters"]] == ["Edited Title"]
    assert [chapter.content for chapter in exported["chapters"]] == ["Chapter body"]


def test_export_novel_preview_from_database_uses_saved_chapters(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "lightbook.db"
    work = create_work(title="Novel Series", author="Author", db_path=db_path)
    book = create_book(
        work_id=int(work["id"]),
        title="Preview Book",
        media_type="novel",
        source_type="novel_txt",
        source_path=str(tmp_path / "source.txt"),
        export_format="epub",
        db_path=db_path,
    )
    chapter = create_novel_chapter(
        book_id=int(book["id"]),
        title="Old Title",
        content="Preview body",
        order_index=1,
        db_path=db_path,
    )
    update_novel_chapter_title(int(chapter["id"]), "Preview Title", db_path=db_path)
    exported: dict[str, object] = {}

    def fake_export_novel_epub(**kwargs):
        exported.update(kwargs)
        output_path = kwargs["output_path"]
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"preview")
        return output_path

    monkeypatch.setattr(batch_export_service, "_load_epub_exporter", lambda: fake_export_novel_epub)
    preview_path = tmp_path / "data" / "previews" / str(book["id"]) / "preview.epub"

    result_path = export_novel_preview_from_database(int(book["id"]), preview_path, db_path=db_path)

    assert result_path == preview_path
    assert preview_path.exists()
    assert exported["book_title"] == "Preview Book"
    assert [chapter.title for chapter in exported["chapters"]] == ["Preview Title"]


def test_export_book_from_database_exports_manga_cbz_without_novel_flow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "lightbook.db"
    source_path = tmp_path / "images"
    work = create_work(title="Manga Series", db_path=db_path)
    book = create_book(
        work_id=int(work["id"]),
        title="Volume 1",
        volume_number=1,
        media_type="comic",
        source_type="image_folder",
        source_path=str(source_path),
        page_count=1,
        export_format="cbz",
        status="ready",
        db_path=db_path,
    )

    monkeypatch.setattr(batch_export_service, "import_image_folder", lambda path: _comic_import_result(Path(path)))
    monkeypatch.setattr(
        batch_export_service,
        "export_cbz",
        lambda import_result, output_root, metadata: ExportResult(
            cbz_path=output_root / "Manga" / "Manga Series" / "Manga Series v01.cbz",
            poster_path=output_root / "Manga" / "Manga Series" / "poster.jpg",
        ),
    )

    output_path = export_book_from_database(int(book["id"]), tmp_path / "out", db_path=db_path)

    assert output_path == tmp_path / "out" / "Manga" / "Manga Series" / "Manga Series v01.cbz"
    assert get_book(int(book["id"]), db_path=db_path)["status"] == "exported"  # type: ignore[index]


def test_export_book_from_database_marks_novel_failed_on_export_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "lightbook.db"
    work = create_work(title="Novel Series", db_path=db_path)
    book = create_book(
        work_id=int(work["id"]),
        title="第一卷",
        volume_number=1,
        media_type="novel",
        source_type="novel_txt",
        source_path=str(tmp_path / "source.txt"),
        export_format="epub",
        status="ready",
        db_path=db_path,
    )
    create_novel_chapter(
        book_id=int(book["id"]),
        title="序章",
        content="正文",
        order_index=1,
        db_path=db_path,
    )
    monkeypatch.setattr(batch_export_service, "_load_epub_exporter", lambda: _raising_epub_exporter)

    with pytest.raises(RuntimeError, match="boom"):
        export_book_from_database(int(book["id"]), tmp_path / "out", db_path=db_path)

    assert get_book(int(book["id"]), db_path=db_path)["status"] == "failed"  # type: ignore[index]


def test_export_book_from_database_rejects_novel_without_chapters(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "lightbook.db"
    work = create_work(title="Novel Series", db_path=db_path)
    book = create_book(
        work_id=int(work["id"]),
        title="Empty",
        media_type="novel",
        source_type="novel_txt",
        source_path=str(tmp_path / "source.txt"),
        export_format="epub",
        status="ready",
        db_path=db_path,
    )

    with pytest.raises(ExporterError, match="没有可导出的小说章节"):
        export_book_from_database(int(book["id"]), tmp_path / "out", db_path=db_path)

    assert get_book(int(book["id"]), db_path=db_path)["status"] == "failed"  # type: ignore[index]


def _comic_import_result(path: Path) -> ImportResult:
    return ImportResult(
        source_path=path,
        source_type="image_folder",
        pages=[ComicPage(display_name="0001.jpg", extension="jpg", source_path=path)],
        cover_data=b"cover",
        cover_extension="jpg",
        metadata=ComicMetadata(series_title="Manga Series", book_title="Volume 1"),
    )


def _raising_epub_exporter(**kwargs):
    raise RuntimeError("boom")
