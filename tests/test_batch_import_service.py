from __future__ import annotations

from pathlib import Path

from app.core.models import ComicMetadata, ComicPage, ImportResult
from app.services.batch_import_service import batch_import
from app.storage.repositories import get_book, list_books, list_works


def test_batch_import_creates_books_and_reuses_work(tmp_path: Path) -> None:
    db_path = tmp_path / "lightbook.db"
    epub_path = tmp_path / "Series v01.epub"
    folder_path = tmp_path / "Series v02"
    folder_path.mkdir()

    result = batch_import(
        [epub_path, folder_path],
        db_path=db_path,
        epub_importer=_mock_epub_importer(page_count=3, metadata_title="Metadata Fallback"),
        image_folder_importer=_mock_folder_importer(page_count=5),
    )

    assert result.imported_count == 2
    assert result.failed_count == 0
    assert result.errors == []
    assert result.book_ids == [1, 2]

    works = list_works(db_path=db_path)
    assert len(works) == 1
    assert works[0]["title"] == "Series"

    books = list_books(db_path=db_path)
    assert [book["work_id"] for book in books] == [works[0]["id"], works[0]["id"]]
    assert [book["title"] for book in books] == ["Series v01", "Series v02"]
    assert [book["volume_number"] for book in books] == [1, 2]
    assert [book["page_count"] for book in books] == [3, 5]
    assert [book["status"] for book in books] == ["need_review", "need_review"]
    assert books[0]["source_type"] == "epub"
    assert books[1]["source_type"] == "image_folder"
    assert books[0]["source_path"] == str(epub_path)
    assert books[1]["source_path"] == str(folder_path)


def test_batch_import_uses_importer_metadata_when_filename_has_no_series(tmp_path: Path) -> None:
    db_path = tmp_path / "lightbook.db"
    epub_path = tmp_path / "v01.epub"

    result = batch_import(
        [epub_path],
        db_path=db_path,
        epub_importer=_mock_epub_importer(page_count=2, metadata_title="Metadata Series"),
        image_folder_importer=_mock_folder_importer(page_count=1),
    )

    assert result.imported_count == 1
    work = list_works(db_path=db_path)[0]
    book = get_book(result.book_ids[0], db_path=db_path)
    assert work["title"] == "Metadata Series"
    assert book is not None
    assert book["title"] == "v01"
    assert book["volume_number"] == 1


def test_batch_import_records_errors_without_stopping_batch(tmp_path: Path) -> None:
    db_path = tmp_path / "lightbook.db"
    good_path = tmp_path / "Good Series v01.epub"
    bad_path = tmp_path / "notes.txt"

    result = batch_import(
        [bad_path, good_path],
        db_path=db_path,
        epub_importer=_mock_epub_importer(page_count=4, metadata_title="Ignored"),
        image_folder_importer=_mock_folder_importer(page_count=1),
    )

    assert result.imported_count == 1
    assert result.failed_count == 1
    assert result.book_ids == [1]
    assert str(bad_path) in result.errors[0]
    assert "unsupported source" in result.errors[0]
    assert len(list_books(db_path=db_path)) == 1


def test_batch_import_records_importer_failure_and_continues(tmp_path: Path) -> None:
    db_path = tmp_path / "lightbook.db"
    failing_path = tmp_path / "Bad v01.epub"
    good_path = tmp_path / "Good v01.epub"

    def failing_epub_importer(path: str | Path) -> ImportResult:
        if Path(path) == failing_path:
            raise RuntimeError("boom")
        return _import_result(Path(path), "epub", 2, "Metadata")

    result = batch_import(
        [failing_path, good_path],
        db_path=db_path,
        epub_importer=failing_epub_importer,
        image_folder_importer=_mock_folder_importer(page_count=1),
    )

    assert result.imported_count == 1
    assert result.failed_count == 1
    assert "boom" in result.errors[0]
    assert len(list_books(db_path=db_path)) == 1


def _mock_epub_importer(page_count: int, metadata_title: str):
    def importer(path: str | Path) -> ImportResult:
        return _import_result(Path(path), "epub", page_count, metadata_title)

    return importer


def _mock_folder_importer(page_count: int):
    def importer(path: str | Path) -> ImportResult:
        return _import_result(Path(path), "image_folder", page_count, Path(path).name)

    return importer


def _import_result(
    path: Path,
    source_type: str,
    page_count: int,
    metadata_title: str,
) -> ImportResult:
    return ImportResult(
        source_path=path,
        source_type=source_type,  # type: ignore[arg-type]
        pages=[
            ComicPage(display_name=f"{index:04d}.jpg", extension="jpg", source_path=path)
            for index in range(1, page_count + 1)
        ],
        cover_data=b"cover",
        cover_extension="jpg",
        metadata=ComicMetadata(
            series_title=metadata_title,
            book_title=metadata_title,
            author="Author",
            summary="Summary",
            genres=["Genre"],
            tags=["Tag"],
            language_iso="zh",
        ),
    )
