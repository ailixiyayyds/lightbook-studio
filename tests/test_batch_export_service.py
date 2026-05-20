from __future__ import annotations

from pathlib import Path

import pytest

from app.core.models import ComicMetadata, ComicPage, ExportResult, ExporterError, ImportResult
from app.importers.novel_txt_importer import NovelImportResult
from app.services import batch_export_service
from app.services.batch_export_service import export_book_from_database
from app.storage.repositories import create_book, create_work, get_book
from app.utils.novel_chapter_parser import NovelChapter, NovelVolume


def test_export_book_from_database_exports_novel_epub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "lightbook.db"
    source_path = tmp_path / "source.txt"
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
        source_path=str(source_path),
        chapter_count=1,
        text_length=20,
        export_format="epub",
        status="ready",
        db_path=db_path,
    )

    monkeypatch.setattr(
        batch_export_service,
        "import_novel_txt",
        lambda path: _novel_import_result(Path(path)),
    )
    exported: dict[str, object] = {}

    def fake_export_novel_epub(**kwargs):
        exported.update(kwargs)
        output_path = kwargs["output_path"]
        output_path.write_bytes(b"epub")
        return output_path

    monkeypatch.setattr(
        batch_export_service,
        "_load_epub_exporter",
        lambda: fake_export_novel_epub,
    )

    output_path = export_book_from_database(
        int(book["id"]),
        tmp_path / "out",
        db_path=db_path,
    )

    assert output_path == tmp_path / "out" / "Novel" / "Novel_Series" / "Novel_Series v01.epub"
    assert output_path.exists()
    assert exported["series_title"] == "Novel:Series"
    assert exported["book_title"] == "第一卷"
    assert exported["volume_number"] == 1
    assert [chapter.title for chapter in exported["chapters"]] == ["第一卷 序章"]
    assert get_book(int(book["id"]), db_path=db_path)["status"] == "exported"  # type: ignore[index]


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
        media_type="manga",
        source_type="image_folder",
        source_path=str(source_path),
        page_count=1,
        export_format="cbz",
        status="ready",
        db_path=db_path,
    )

    monkeypatch.setattr(
        batch_export_service,
        "import_image_folder",
        lambda path: _comic_import_result(Path(path)),
    )
    monkeypatch.setattr(
        batch_export_service,
        "export_cbz",
        lambda import_result, output_root, metadata: ExportResult(
            cbz_path=output_root / "Manga" / "Manga Series" / "Manga Series v01.cbz",
            poster_path=output_root / "Manga" / "Manga Series" / "poster.jpg",
        ),
    )
    monkeypatch.setattr(
        batch_export_service,
        "import_novel_txt",
        lambda path: pytest.fail("novel importer should not be used for manga"),
    )

    output_path = export_book_from_database(
        int(book["id"]),
        tmp_path / "out",
        db_path=db_path,
    )

    assert output_path == tmp_path / "out" / "Manga" / "Manga Series" / "Manga Series v01.cbz"
    assert get_book(int(book["id"]), db_path=db_path)["status"] == "exported"  # type: ignore[index]


def test_export_book_from_database_marks_novel_failed_on_export_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "lightbook.db"
    source_path = tmp_path / "source.txt"
    work = create_work(title="Novel Series", db_path=db_path)
    book = create_book(
        work_id=int(work["id"]),
        title="第一卷",
        volume_number=1,
        media_type="novel",
        source_type="novel_txt",
        source_path=str(source_path),
        export_format="epub",
        status="ready",
        db_path=db_path,
    )

    monkeypatch.setattr(
        batch_export_service,
        "import_novel_txt",
        lambda path: _novel_import_result(Path(path)),
    )
    monkeypatch.setattr(
        batch_export_service,
        "_load_epub_exporter",
        lambda: _raising_epub_exporter,
    )

    with pytest.raises(RuntimeError, match="boom"):
        export_book_from_database(int(book["id"]), tmp_path / "out", db_path=db_path)

    assert get_book(int(book["id"]), db_path=db_path)["status"] == "failed"  # type: ignore[index]


def test_export_book_from_database_rejects_novel_without_chapters(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "lightbook.db"
    source_path = tmp_path / "source.txt"
    work = create_work(title="Novel Series", db_path=db_path)
    book = create_book(
        work_id=int(work["id"]),
        title="Empty",
        media_type="novel",
        source_type="novel_txt",
        source_path=str(source_path),
        export_format="epub",
        status="ready",
        db_path=db_path,
    )

    monkeypatch.setattr(
        batch_export_service,
        "import_novel_txt",
        lambda path: NovelImportResult(
            source_path=Path(path),
            encoding="utf-8",
            title_guess="Novel Series",
            volumes=[],
            text_length=0,
            chapter_count=0,
            warnings=["没识别到章节"],
        ),
    )

    with pytest.raises(ExporterError, match="没识别到章节"):
        export_book_from_database(int(book["id"]), tmp_path / "out", db_path=db_path)

    assert get_book(int(book["id"]), db_path=db_path)["status"] == "failed"  # type: ignore[index]


def _novel_import_result(path: Path) -> NovelImportResult:
    return NovelImportResult(
        source_path=path,
        source_file_id=None,
        source_book_id=None,
        encoding="utf-8",
        title_guess="Novel Series",
        author_guess="Author",
        volumes=[
            NovelVolume(
                title="第一卷",
                volume_number=1,
                chapters=[NovelChapter(title="序章", content="正文", index=1)],
            )
        ],
        text_length=2,
        chapter_count=1,
        warnings=[],
    )


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
