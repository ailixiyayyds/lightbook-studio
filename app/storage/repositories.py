from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.storage.database import DEFAULT_DATABASE_PATH, connect

RowDict = dict[str, Any]


def create_work(
    *,
    title: str,
    original_title: str = "",
    author: str = "",
    summary: str = "",
    genres: str = "",
    tags: str = "",
    language_iso: str = "zh",
    db_path: str | Path = DEFAULT_DATABASE_PATH,
) -> RowDict:
    timestamp = _now()
    with closing(connect(db_path)) as connection, connection:
        cursor = connection.execute(
            """
            INSERT INTO works (
              title, original_title, author, summary, genres, tags,
              language_iso, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                title,
                original_title,
                author,
                summary,
                genres,
                tags,
                language_iso,
                timestamp,
                timestamp,
            ),
        )
        return _get_required_by_id(connection, "works", int(cursor.lastrowid))


def update_work(
    work_id: int,
    *,
    title: str | None = None,
    original_title: str | None = None,
    author: str | None = None,
    summary: str | None = None,
    genres: str | None = None,
    tags: str | None = None,
    language_iso: str | None = None,
    db_path: str | Path = DEFAULT_DATABASE_PATH,
) -> RowDict | None:
    updates = _without_none(
        {
            "title": title,
            "original_title": original_title,
            "author": author,
            "summary": summary,
            "genres": genres,
            "tags": tags,
            "language_iso": language_iso,
        }
    )
    return _update_row("works", work_id, updates, db_path)


def get_work(
    work_id: int,
    *,
    db_path: str | Path = DEFAULT_DATABASE_PATH,
) -> RowDict | None:
    with closing(connect(db_path)) as connection, connection:
        row = connection.execute("SELECT * FROM works WHERE id = ?", (work_id,)).fetchone()
        return _row_to_dict(row)


def delete_work(
    work_id: int,
    *,
    db_path: str | Path = DEFAULT_DATABASE_PATH,
) -> bool:
    with closing(connect(db_path)) as connection, connection:
        cursor = connection.execute("DELETE FROM works WHERE id = ?", (work_id,))
        return cursor.rowcount > 0


def list_works(
    *,
    db_path: str | Path = DEFAULT_DATABASE_PATH,
) -> list[RowDict]:
    with closing(connect(db_path)) as connection, connection:
        rows = connection.execute("SELECT * FROM works ORDER BY id").fetchall()
        return [_row_to_dict_required(row) for row in rows]


def create_book(
    *,
    work_id: int,
    source_type: str,
    source_path: str,
    title: str = "",
    volume_number: int | None = None,
    page_count: int = 0,
    cover_path: str = "",
    translator: str = "",
    manga_direction: str = "rtl",
    status: str = "need_review",
    db_path: str | Path = DEFAULT_DATABASE_PATH,
) -> RowDict:
    timestamp = _now()
    with closing(connect(db_path)) as connection, connection:
        cursor = connection.execute(
            """
            INSERT INTO books (
              work_id, title, volume_number, source_type, source_path,
              page_count, cover_path, translator, manga_direction,
              status, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                work_id,
                title,
                volume_number,
                source_type,
                source_path,
                page_count,
                cover_path,
                translator,
                manga_direction,
                status,
                timestamp,
                timestamp,
            ),
        )
        return _get_required_by_id(connection, "books", int(cursor.lastrowid))


def update_book(
    book_id: int,
    *,
    work_id: int | None = None,
    title: str | None = None,
    volume_number: int | None = None,
    source_type: str | None = None,
    source_path: str | None = None,
    page_count: int | None = None,
    cover_path: str | None = None,
    translator: str | None = None,
    manga_direction: str | None = None,
    status: str | None = None,
    db_path: str | Path = DEFAULT_DATABASE_PATH,
) -> RowDict | None:
    updates = _without_none(
        {
            "work_id": work_id,
            "title": title,
            "volume_number": volume_number,
            "source_type": source_type,
            "source_path": source_path,
            "page_count": page_count,
            "cover_path": cover_path,
            "translator": translator,
            "manga_direction": manga_direction,
            "status": status,
        }
    )
    return _update_row("books", book_id, updates, db_path)


def get_book(
    book_id: int,
    *,
    db_path: str | Path = DEFAULT_DATABASE_PATH,
) -> RowDict | None:
    with closing(connect(db_path)) as connection, connection:
        row = connection.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
        return _row_to_dict(row)


def delete_book(
    book_id: int,
    *,
    db_path: str | Path = DEFAULT_DATABASE_PATH,
) -> bool:
    with closing(connect(db_path)) as connection, connection:
        connection.execute("DELETE FROM export_jobs WHERE book_id = ?", (book_id,))
        cursor = connection.execute("DELETE FROM books WHERE id = ?", (book_id,))
        return cursor.rowcount > 0


def list_books(
    *,
    db_path: str | Path = DEFAULT_DATABASE_PATH,
) -> list[RowDict]:
    with closing(connect(db_path)) as connection, connection:
        rows = connection.execute("SELECT * FROM books ORDER BY id").fetchall()
        return [_row_to_dict_required(row) for row in rows]


def list_books_by_work(
    work_id: int,
    *,
    db_path: str | Path = DEFAULT_DATABASE_PATH,
) -> list[RowDict]:
    with closing(connect(db_path)) as connection, connection:
        rows = connection.execute(
            "SELECT * FROM books WHERE work_id = ? ORDER BY id",
            (work_id,),
        ).fetchall()
        return [_row_to_dict_required(row) for row in rows]


def list_books_by_status(
    status: str,
    *,
    db_path: str | Path = DEFAULT_DATABASE_PATH,
) -> list[RowDict]:
    with closing(connect(db_path)) as connection, connection:
        rows = connection.execute(
            "SELECT * FROM books WHERE status = ? ORDER BY id",
            (status,),
        ).fetchall()
        return [_row_to_dict_required(row) for row in rows]


def create_export_job(
    *,
    book_id: int,
    output_path: str,
    status: str = "pending",
    error_message: str = "",
    db_path: str | Path = DEFAULT_DATABASE_PATH,
) -> RowDict:
    timestamp = _now()
    with closing(connect(db_path)) as connection, connection:
        cursor = connection.execute(
            """
            INSERT INTO export_jobs (
              book_id, output_path, status, error_message, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (book_id, output_path, status, error_message, timestamp, timestamp),
        )
        return _get_required_by_id(connection, "export_jobs", int(cursor.lastrowid))


def update_export_job(
    export_job_id: int,
    *,
    book_id: int | None = None,
    output_path: str | None = None,
    status: str | None = None,
    error_message: str | None = None,
    db_path: str | Path = DEFAULT_DATABASE_PATH,
) -> RowDict | None:
    updates = _without_none(
        {
            "book_id": book_id,
            "output_path": output_path,
            "status": status,
            "error_message": error_message,
        }
    )
    return _update_row("export_jobs", export_job_id, updates, db_path)


def get_setting(
    key: str,
    *,
    db_path: str | Path = DEFAULT_DATABASE_PATH,
) -> str | None:
    with closing(connect(db_path)) as connection, connection:
        row = connection.execute(
            "SELECT value FROM app_settings WHERE key = ?",
            (key,),
        ).fetchone()
        if row is None:
            return None
        return str(row["value"])


def set_setting(
    key: str,
    value: str,
    *,
    db_path: str | Path = DEFAULT_DATABASE_PATH,
) -> None:
    with closing(connect(db_path)) as connection, connection:
        connection.execute(
            """
            INSERT INTO app_settings (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )


def _update_row(
    table_name: str,
    row_id: int,
    updates: dict[str, Any],
    db_path: str | Path,
) -> RowDict | None:
    values = {**updates, "updated_at": _now()}
    assignments = ", ".join(f"{column} = ?" for column in values)
    parameters = [*values.values(), row_id]
    with closing(connect(db_path)) as connection, connection:
        connection.execute(
            f"UPDATE {table_name} SET {assignments} WHERE id = ?",
            parameters,
        )
        row = connection.execute(
            f"SELECT * FROM {table_name} WHERE id = ?",
            (row_id,),
        ).fetchone()
        return _row_to_dict(row)


def _get_required_by_id(connection: sqlite3.Connection, table_name: str, row_id: int) -> RowDict:
    row = connection.execute(
        f"SELECT * FROM {table_name} WHERE id = ?",
        (row_id,),
    ).fetchone()
    return _row_to_dict_required(row)


def _without_none(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


def _row_to_dict(row: sqlite3.Row | None) -> RowDict | None:
    if row is None:
        return None
    return dict(row)


def _row_to_dict_required(row: sqlite3.Row | None) -> RowDict:
    if row is None:
        raise LookupError("Expected row was not found.")
    return dict(row)


def _now() -> str:
    return datetime.now(UTC).isoformat()
