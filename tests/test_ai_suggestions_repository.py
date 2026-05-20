from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

from app.storage.database import initialize_database
from app.storage.repositories import (
    create_ai_suggestion,
    create_book,
    create_work,
    delete_ai_suggestions_by_book,
    delete_book,
    get_ai_suggestion,
    list_ai_suggestions_by_book,
    list_latest_ai_suggestion_by_book,
    update_ai_suggestion,
)


def test_ai_suggestions_table_is_created_by_migration(tmp_path: Path) -> None:
    db_path = tmp_path / "lightbook.db"
    _create_legacy_database_without_ai_suggestions(db_path)

    initialize_database(db_path)

    with closing(sqlite3.connect(db_path)) as connection:
        connection.row_factory = sqlite3.Row
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        columns = {
            row[1]: row
            for row in connection.execute("PRAGMA table_info(ai_suggestions)").fetchall()
        }
        book = connection.execute("SELECT * FROM books WHERE id = 1").fetchone()

    assert "ai_suggestions" in tables
    assert {
        "id",
        "book_id",
        "provider",
        "status",
        "input_snapshot",
        "raw_response",
        "parsed_json",
        "confidence",
        "error_message",
        "created_at",
        "updated_at",
    }.issubset(columns)
    assert columns["status"][4] == "'pending'"
    assert columns["input_snapshot"][4] == "'{}'"
    assert columns["parsed_json"][4] == "'{}'"
    assert book["title"] == "Existing Book"


def test_ai_suggestion_repository_crud_and_latest(tmp_path: Path) -> None:
    db_path = tmp_path / "lightbook.db"
    work = create_work(title="Series", db_path=db_path)
    book = create_book(
        work_id=int(work["id"]),
        title="Volume 1",
        source_type="epub",
        source_path="C:/Books/book.epub",
        db_path=db_path,
    )

    first = create_ai_suggestion(
        book_id=int(book["id"]),
        provider="mock",
        input_snapshot={"title": "Raw Title"},
        parsed_json={"clean_title": "Clean Title"},
        confidence=0.75,
        db_path=db_path,
    )
    second = create_ai_suggestion(
        book_id=int(book["id"]),
        provider="mock",
        status="running",
        input_snapshot="{}",
        raw_response='{"clean_title":"Second"}',
        parsed_json={"clean_title": "Second"},
        confidence=0.8,
        db_path=db_path,
    )

    assert first["status"] == "pending"
    assert json.loads(str(first["input_snapshot"])) == {"title": "Raw Title"}
    assert json.loads(str(first["parsed_json"])) == {"clean_title": "Clean Title"}
    assert first["raw_response"] == ""
    assert first["error_message"] == ""
    assert first["created_at"]
    assert first["updated_at"]

    updated = update_ai_suggestion(
        int(first["id"]),
        status="completed",
        raw_response='{"clean_title":"Updated"}',
        parsed_json={"clean_title": "Updated", "tags": ["fantasy"]},
        confidence=0.9,
        db_path=db_path,
    )

    assert updated is not None
    assert updated["status"] == "completed"
    assert updated["confidence"] == 0.9
    assert json.loads(str(updated["parsed_json"])) == {
        "clean_title": "Updated",
        "tags": ["fantasy"],
    }

    assert get_ai_suggestion(int(first["id"]), db_path=db_path) == updated
    assert [row["id"] for row in list_ai_suggestions_by_book(int(book["id"]), db_path=db_path)] == [
        first["id"],
        second["id"],
    ]
    assert list_latest_ai_suggestion_by_book(int(book["id"]), db_path=db_path)["id"] == second["id"]  # type: ignore[index]


def test_delete_ai_suggestions_by_book(tmp_path: Path) -> None:
    db_path = tmp_path / "lightbook.db"
    work = create_work(title="Series", db_path=db_path)
    first_book = create_book(
        work_id=int(work["id"]),
        title="Volume 1",
        source_type="epub",
        source_path="C:/Books/book-1.epub",
        db_path=db_path,
    )
    second_book = create_book(
        work_id=int(work["id"]),
        title="Volume 2",
        source_type="epub",
        source_path="C:/Books/book-2.epub",
        db_path=db_path,
    )
    create_ai_suggestion(book_id=int(first_book["id"]), provider="mock", db_path=db_path)
    create_ai_suggestion(book_id=int(first_book["id"]), provider="mock", db_path=db_path)
    remaining = create_ai_suggestion(book_id=int(second_book["id"]), provider="mock", db_path=db_path)

    assert delete_ai_suggestions_by_book(int(first_book["id"]), db_path=db_path) == 2

    assert list_ai_suggestions_by_book(int(first_book["id"]), db_path=db_path) == []
    assert [row["id"] for row in list_ai_suggestions_by_book(int(second_book["id"]), db_path=db_path)] == [
        remaining["id"],
    ]


def test_delete_book_removes_related_ai_suggestions(tmp_path: Path) -> None:
    db_path = tmp_path / "lightbook.db"
    work = create_work(title="Series", db_path=db_path)
    book = create_book(
        work_id=int(work["id"]),
        title="Volume 1",
        source_type="epub",
        source_path="C:/Books/book.epub",
        db_path=db_path,
    )
    create_ai_suggestion(book_id=int(book["id"]), provider="mock", db_path=db_path)

    assert delete_book(int(book["id"]), db_path=db_path) is True
    assert list_ai_suggestions_by_book(int(book["id"]), db_path=db_path) == []


def _create_legacy_database_without_ai_suggestions(db_path: Path) -> None:
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
