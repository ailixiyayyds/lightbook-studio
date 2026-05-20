from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from app.storage.database import initialize_database
from app.storage.repositories import (
    create_book,
    create_export_job,
    create_novel_chapter,
    create_work,
    delete_book,
    delete_books,
    delete_novel_chapters_by_book,
    delete_work,
    get_book,
    get_setting,
    get_work,
    list_books,
    list_books_by_status,
    list_books_by_work,
    list_novel_chapters,
    list_works,
    bulk_update_book_status,
    set_setting,
    update_book,
    update_book_cover_override,
    update_export_job,
    update_novel_chapter_title,
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
    assert {"works", "books", "export_jobs", "app_settings", "novel_chapters"}.issubset(tables)


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
    assert book["media_type"] == "comic"
    assert book["chapter_count"] == 0
    assert book["text_length"] == 0
    assert book["export_format"] == "cbz"
    assert book["cover_override_path"] == ""
    assert get_book(book["id"], db_path=db_path) == book
    assert list_books(db_path=db_path) == [book]
    assert list_books_by_status("need_review", db_path=db_path) == [book]
    assert list_books_by_status("exported", db_path=db_path) == []

    updated = update_book(
        book["id"],
        status="ready",
        media_type="novel",
        page_count=121,
        chapter_count=12,
        text_length=3456,
        export_format="epub",
        db_path=db_path,
    )

    assert updated is not None
    assert updated["status"] == "ready"
    assert updated["media_type"] == "novel"
    assert updated["page_count"] == 121
    assert updated["chapter_count"] == 12
    assert updated["text_length"] == 3456
    assert updated["export_format"] == "epub"
    assert list_books_by_status("ready", db_path=db_path) == [updated]

    cleared = update_book(book["id"], volume_number=None, db_path=db_path)
    assert cleared is not None
    assert cleared["volume_number"] is None

    cover_updated = update_book_cover_override(
        book["id"],
        "C:/Covers/custom.jpg",
        db_path=db_path,
    )
    assert cover_updated is not None
    assert cover_updated["cover_override_path"] == "C:/Covers/custom.jpg"


def test_initialize_database_migrates_existing_books_table(tmp_path: Path) -> None:
    db_path = tmp_path / "lightbook.db"
    with closing(sqlite3.connect(db_path)) as connection:
        connection.executescript(
            """
            CREATE TABLE works (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              title TEXT NOT NULL,
              original_title TEXT DEFAULT '',
              author TEXT DEFAULT '',
              summary TEXT DEFAULT '',
              genres TEXT DEFAULT '',
              tags TEXT DEFAULT '',
              language_iso TEXT DEFAULT 'zh',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE books (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              work_id INTEGER NOT NULL,
              title TEXT DEFAULT '',
              volume_number INTEGER,
              source_type TEXT NOT NULL,
              source_path TEXT NOT NULL,
              page_count INTEGER DEFAULT 0,
              cover_path TEXT DEFAULT '',
              status TEXT NOT NULL DEFAULT 'need_review',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            """
        )

    initialize_database(db_path)

    with closing(sqlite3.connect(db_path)) as connection:
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(books)").fetchall()
        }

    assert {
        "media_type",
        "translator",
        "manga_direction",
        "chapter_count",
        "text_length",
        "export_format",
        "cover_override_path",
    }.issubset(columns)

    with closing(sqlite3.connect(db_path)) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    assert "novel_chapters" in tables


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


def test_novel_chapter_repository_crud(tmp_path: Path) -> None:
    db_path = tmp_path / "lightbook.db"
    work = create_work(title="Novel", db_path=db_path)
    book = create_book(
        work_id=work["id"],
        media_type="novel",
        source_type="novel_txt",
        source_path="C:/Novel/source.txt",
        export_format="epub",
        db_path=db_path,
    )

    second = create_novel_chapter(
        book_id=book["id"],
        title="第二章",
        content="二",
        order_index=2,
        db_path=db_path,
    )
    first = create_novel_chapter(
        book_id=book["id"],
        title="第一章",
        content="一",
        order_index=1,
        db_path=db_path,
    )

    assert [chapter["id"] for chapter in list_novel_chapters(book["id"], db_path=db_path)] == [
        first["id"],
        second["id"],
    ]

    updated = update_novel_chapter_title(first["id"], "序章", db_path=db_path)
    assert updated is not None
    assert updated["title"] == "序章"
    assert updated["content"] == "一"

    assert delete_novel_chapters_by_book(book["id"], db_path=db_path) == 2
    assert list_novel_chapters(book["id"], db_path=db_path) == []


def test_bulk_update_status_and_delete_books_remove_database_rows_only(tmp_path: Path) -> None:
    db_path = tmp_path / "lightbook.db"
    source_file = tmp_path / "source.txt"
    source_file.write_text("local source", encoding="utf-8")
    work = create_work(title="Novel", db_path=db_path)
    first = create_book(
        work_id=work["id"],
        media_type="novel",
        source_type="novel_txt",
        source_path=str(source_file),
        export_format="epub",
        db_path=db_path,
    )
    second = create_book(
        work_id=work["id"],
        source_type="epub",
        source_path="C:/Comic/book.epub",
        db_path=db_path,
    )
    create_novel_chapter(
        book_id=first["id"],
        title="第一章",
        content="内容",
        order_index=1,
        db_path=db_path,
    )
    create_export_job(book_id=first["id"], output_path="C:/Out/book.epub", db_path=db_path)

    assert bulk_update_book_status([first["id"], second["id"]], "ready", db_path=db_path) == 2
    assert [book["status"] for book in list_books_by_status("ready", db_path=db_path)] == [
        "ready",
        "ready",
    ]

    assert delete_books([first["id"]], db_path=db_path) == 1
    assert get_book(first["id"], db_path=db_path) is None
    assert get_book(second["id"], db_path=db_path) is not None
    assert list_novel_chapters(first["id"], db_path=db_path) == []
    with closing(sqlite3.connect(db_path)) as connection:
        jobs = connection.execute(
            "SELECT * FROM export_jobs WHERE book_id = ?",
            (first["id"],),
        ).fetchall()
    assert jobs == []
    assert source_file.exists()


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
