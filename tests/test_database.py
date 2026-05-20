from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from app.storage.database import initialize_database
from app.storage.repositories import (
    create_book,
    create_export_job,
    create_work,
    delete_book,
    delete_work,
    get_book,
    get_setting,
    get_work,
    list_books,
    list_books_by_status,
    list_books_by_work,
    list_works,
    set_setting,
    update_book,
    update_export_job,
    update_work,
)


def test_initialize_database_creates_file_and_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "data" / "lightbook.db"

    initialize_database(db_path)

    assert db_path.exists()
    with closing(sqlite3.connect(db_path)) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    assert {"works", "books", "export_jobs", "app_settings"}.issubset(tables)


def test_work_repository_crud(tmp_path: Path) -> None:
    db_path = tmp_path / "lightbook.db"

    work = create_work(
        title="Light Book",
        original_title="Original",
        author="Author",
        summary="Summary",
        genres="Fantasy, Drama",
        tags="tag-a, tag-b",
        language_iso="zh",
        db_path=db_path,
    )

    assert work["id"] == 1
    assert work["title"] == "Light Book"
    assert work["created_at"]
    assert work["updated_at"]
    assert get_work(work["id"], db_path=db_path) == work
    assert list_works(db_path=db_path) == [work]

    updated = update_work(
        work["id"],
        title="Light Book Updated",
        tags="updated",
        db_path=db_path,
    )

    assert updated is not None
    assert updated["title"] == "Light Book Updated"
    assert updated["author"] == "Author"
    assert updated["tags"] == "updated"


def test_book_repository_crud_and_status_filter(tmp_path: Path) -> None:
    db_path = tmp_path / "lightbook.db"
    work = create_work(title="Series", db_path=db_path)

    book = create_book(
        work_id=work["id"],
        title="Volume 1",
        volume_number=1,
        source_type="image_folder",
        source_path="C:/Manga/Series",
        page_count=120,
        cover_path="poster.jpg",
        db_path=db_path,
    )

    assert book["status"] == "need_review"
    assert get_book(book["id"], db_path=db_path) == book
    assert list_books(db_path=db_path) == [book]
    assert list_books_by_status("need_review", db_path=db_path) == [book]
    assert list_books_by_status("exported", db_path=db_path) == []

    updated = update_book(book["id"], status="ready", page_count=121, db_path=db_path)

    assert updated is not None
    assert updated["status"] == "ready"
    assert updated["page_count"] == 121
    assert list_books_by_status("ready", db_path=db_path) == [updated]


def test_delete_book_and_empty_work(tmp_path: Path) -> None:
    db_path = tmp_path / "lightbook.db"
    work = create_work(title="Series", db_path=db_path)
    book = create_book(
        work_id=work["id"],
        source_type="epub",
        source_path="C:/Manga/book.epub",
        db_path=db_path,
    )
    create_export_job(book_id=book["id"], output_path="C:/Out/book.cbz", db_path=db_path)

    assert list_books_by_work(work["id"], db_path=db_path) == [book]
    assert delete_book(book["id"], db_path=db_path) is True
    assert get_book(book["id"], db_path=db_path) is None
    assert list_books_by_work(work["id"], db_path=db_path) == []
    assert delete_work(work["id"], db_path=db_path) is True
    assert get_work(work["id"], db_path=db_path) is None


def test_export_job_repository_crud(tmp_path: Path) -> None:
    db_path = tmp_path / "lightbook.db"
    work = create_work(title="Series", db_path=db_path)
    book = create_book(
        work_id=work["id"],
        source_type="epub",
        source_path="C:/Manga/book.epub",
        db_path=db_path,
    )

    job = create_export_job(
        book_id=book["id"],
        output_path="C:/Out/Manga/Series/Series v01.cbz",
        db_path=db_path,
    )

    assert job["status"] == "pending"
    assert job["error_message"] == ""

    updated = update_export_job(
        job["id"],
        status="failed",
        error_message="No pages",
        db_path=db_path,
    )

    assert updated is not None
    assert updated["status"] == "failed"
    assert updated["error_message"] == "No pages"


def test_settings_repository_upserts_values(tmp_path: Path) -> None:
    db_path = tmp_path / "lightbook.db"

    assert get_setting("recent_output_dir", db_path=db_path) is None

    set_setting("recent_output_dir", "C:/Out", db_path=db_path)
    assert get_setting("recent_output_dir", db_path=db_path) == "C:/Out"

    set_setting("recent_output_dir", "D:/Out", db_path=db_path)
    assert get_setting("recent_output_dir", db_path=db_path) == "D:/Out"
