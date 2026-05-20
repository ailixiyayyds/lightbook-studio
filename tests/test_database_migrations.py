from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from app.storage.database import initialize_database


def test_migration_adds_v031_book_columns_and_novel_chapters_table(tmp_path: Path) -> None:
    db_path = tmp_path / "lightbook.db"
    _create_v02_database(db_path)

    initialize_database(db_path)

    with closing(sqlite3.connect(db_path)) as connection:
        connection.row_factory = sqlite3.Row
        book_columns = {
            row[1]: row
            for row in connection.execute("PRAGMA table_info(books)").fetchall()
        }
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        novel_chapter_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(novel_chapters)").fetchall()
        }
        book = connection.execute("SELECT * FROM books WHERE id = 1").fetchone()

    assert "cover_override_path" in book_columns
    assert "media_type" in book_columns
    assert "export_format" in book_columns
    assert book_columns["cover_override_path"][4] == "''"
    assert book["title"] == "Existing Book"
    assert "novel_chapters" in tables
    assert {
        "id",
        "book_id",
        "title",
        "content",
        "order_index",
        "created_at",
        "updated_at",
    }.issubset(novel_chapter_columns)


def test_new_database_schema_has_v031_defaults(tmp_path: Path) -> None:
    db_path = tmp_path / "lightbook.db"

    initialize_database(db_path)

    with closing(sqlite3.connect(db_path)) as connection:
        columns = {
            row[1]: row
            for row in connection.execute("PRAGMA table_info(books)").fetchall()
        }

    assert columns["cover_override_path"][4] == "''"
    assert columns["media_type"][4] == "'comic'"
    assert columns["export_format"][4] == "''"


def _create_v02_database(db_path: Path) -> None:
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
              updated_at TEXT NOT NULL,
              FOREIGN KEY(work_id) REFERENCES works(id)
            );
            CREATE TABLE export_jobs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              book_id INTEGER NOT NULL,
              output_path TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'pending',
              error_message TEXT DEFAULT '',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              FOREIGN KEY(book_id) REFERENCES books(id)
            );
            CREATE TABLE app_settings (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            );
            INSERT INTO works (title, created_at, updated_at)
            VALUES ('Existing Work', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z');
            INSERT INTO books (
              work_id, title, source_type, source_path, page_count, created_at, updated_at
            )
            VALUES (
              1, 'Existing Book', 'epub', 'C:/Books/existing.epub', 10,
              '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z'
            );
            """
        )
