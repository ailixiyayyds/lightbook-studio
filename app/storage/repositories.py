from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.storage.database import DEFAULT_DATABASE_PATH, connect

RowDict = dict[str, Any]
_UNSET = object()


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
    media_type: str = "comic",
    page_count: int = 0,
    chapter_count: int = 0,
    text_length: int = 0,
    export_format: str = "cbz",
    cover_path: str = "",
    cover_override_path: str = "",
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
              work_id, title, volume_number, media_type, source_type, source_path,
              page_count, chapter_count, text_length, export_format,
              cover_path, cover_override_path, translator, manga_direction,
              status, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                work_id,
                title,
                volume_number,
                media_type,
                source_type,
                source_path,
                page_count,
                chapter_count,
                text_length,
                export_format,
                cover_path,
                cover_override_path,
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
    volume_number: int | None | object = _UNSET,
    media_type: str | None = None,
    source_type: str | None = None,
    source_path: str | None = None,
    page_count: int | None = None,
    chapter_count: int | None = None,
    text_length: int | None = None,
    export_format: str | None = None,
    cover_path: str | None = None,
    cover_override_path: str | None = None,
    translator: str | None = None,
    manga_direction: str | None = None,
    status: str | None = None,
    db_path: str | Path = DEFAULT_DATABASE_PATH,
) -> RowDict | None:
    updates = _without_none(
        {
            "work_id": work_id,
            "title": title,
            "media_type": media_type,
            "source_type": source_type,
            "source_path": source_path,
            "page_count": page_count,
            "chapter_count": chapter_count,
            "text_length": text_length,
            "export_format": export_format,
            "cover_path": cover_path,
            "cover_override_path": cover_override_path,
            "translator": translator,
            "manga_direction": manga_direction,
            "status": status,
        }
    )
    if volume_number is not _UNSET:
        updates["volume_number"] = volume_number
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
        connection.execute("DELETE FROM ai_suggestions WHERE book_id = ?", (book_id,))
        connection.execute("DELETE FROM novel_chapters WHERE book_id = ?", (book_id,))
        connection.execute("DELETE FROM export_jobs WHERE book_id = ?", (book_id,))
        connection.execute("DELETE FROM metadata_search_results WHERE book_id = ?", (book_id,))
        connection.execute("DELETE FROM ai_request_logs WHERE book_id = ?", (book_id,))
        cursor = connection.execute("DELETE FROM books WHERE id = ?", (book_id,))
        return cursor.rowcount > 0


def delete_books(
    book_ids: list[int],
    *,
    db_path: str | Path = DEFAULT_DATABASE_PATH,
) -> int:
    ids = _clean_ids(book_ids)
    if not ids:
        return 0
    placeholders = _placeholders(ids)
    with closing(connect(db_path)) as connection, connection:
        connection.execute(
            f"DELETE FROM ai_suggestions WHERE book_id IN ({placeholders})",
            ids,
        )
        connection.execute(
            f"DELETE FROM novel_chapters WHERE book_id IN ({placeholders})",
            ids,
        )
        connection.execute(
            f"DELETE FROM export_jobs WHERE book_id IN ({placeholders})",
            ids,
        )
        connection.execute(
            f"DELETE FROM metadata_search_results WHERE book_id IN ({placeholders})",
            ids,
        )
        connection.execute(
            f"DELETE FROM ai_request_logs WHERE book_id IN ({placeholders})",
            ids,
        )
        cursor = connection.execute(
            f"DELETE FROM books WHERE id IN ({placeholders})",
            ids,
        )
        return cursor.rowcount


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


def bulk_update_book_status(
    book_ids: list[int],
    status: str,
    *,
    db_path: str | Path = DEFAULT_DATABASE_PATH,
) -> int:
    ids = _clean_ids(book_ids)
    if not ids:
        return 0
    placeholders = _placeholders(ids)
    with closing(connect(db_path)) as connection, connection:
        cursor = connection.execute(
            f"UPDATE books SET status = ?, updated_at = ? WHERE id IN ({placeholders})",
            [status, _now(), *ids],
        )
        return cursor.rowcount


def update_book_cover_override(
    book_id: int,
    cover_override_path: str,
    *,
    db_path: str | Path = DEFAULT_DATABASE_PATH,
) -> RowDict | None:
    return update_book(
        book_id,
        cover_override_path=cover_override_path,
        db_path=db_path,
    )


def create_novel_chapter(
    *,
    book_id: int,
    title: str,
    content: str,
    order_index: int,
    db_path: str | Path = DEFAULT_DATABASE_PATH,
) -> RowDict:
    timestamp = _now()
    with closing(connect(db_path)) as connection, connection:
        cursor = connection.execute(
            """
            INSERT INTO novel_chapters (
              book_id, title, content, order_index, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (book_id, title, content, order_index, timestamp, timestamp),
        )
        return _get_required_by_id(connection, "novel_chapters", int(cursor.lastrowid))


def update_novel_chapter_title(
    chapter_id: int,
    title: str,
    *,
    db_path: str | Path = DEFAULT_DATABASE_PATH,
) -> RowDict | None:
    return _update_row("novel_chapters", chapter_id, {"title": title}, db_path)


def list_novel_chapters(
    book_id: int,
    *,
    db_path: str | Path = DEFAULT_DATABASE_PATH,
) -> list[RowDict]:
    with closing(connect(db_path)) as connection, connection:
        rows = connection.execute(
            """
            SELECT * FROM novel_chapters
            WHERE book_id = ?
            ORDER BY order_index, id
            """,
            (book_id,),
        ).fetchall()
        return [_row_to_dict_required(row) for row in rows]


def delete_novel_chapters_by_book(
    book_id: int,
    *,
    db_path: str | Path = DEFAULT_DATABASE_PATH,
) -> int:
    with closing(connect(db_path)) as connection, connection:
        cursor = connection.execute(
            "DELETE FROM novel_chapters WHERE book_id = ?",
            (book_id,),
        )
        return cursor.rowcount


def create_ai_suggestion(
    *,
    book_id: int,
    provider: str,
    status: str = "pending",
    input_snapshot: Any = "{}",
    raw_response: str = "",
    parsed_json: Any = "{}",
    confidence: float = 0,
    error_message: str = "",
    db_path: str | Path = DEFAULT_DATABASE_PATH,
) -> RowDict:
    timestamp = _now()
    with closing(connect(db_path)) as connection, connection:
        cursor = connection.execute(
            """
            INSERT INTO ai_suggestions (
              book_id, provider, status, input_snapshot, raw_response,
              parsed_json, confidence, error_message, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                book_id,
                provider,
                status,
                _json_text(input_snapshot),
                raw_response,
                _json_text(parsed_json),
                float(confidence),
                error_message,
                timestamp,
                timestamp,
            ),
        )
        return _get_required_by_id(connection, "ai_suggestions", int(cursor.lastrowid))


def update_ai_suggestion(
    ai_suggestion_id: int,
    *,
    book_id: int | None = None,
    provider: str | None = None,
    status: str | None = None,
    input_snapshot: Any | None = None,
    raw_response: str | None = None,
    parsed_json: Any | None = None,
    confidence: float | None = None,
    error_message: str | None = None,
    db_path: str | Path = DEFAULT_DATABASE_PATH,
) -> RowDict | None:
    updates = _without_none(
        {
            "book_id": book_id,
            "provider": provider,
            "status": status,
            "input_snapshot": _json_text(input_snapshot) if input_snapshot is not None else None,
            "raw_response": raw_response,
            "parsed_json": _json_text(parsed_json) if parsed_json is not None else None,
            "confidence": confidence,
            "error_message": error_message,
        }
    )
    return _update_row("ai_suggestions", ai_suggestion_id, updates, db_path)


def get_ai_suggestion(
    ai_suggestion_id: int,
    *,
    db_path: str | Path = DEFAULT_DATABASE_PATH,
) -> RowDict | None:
    with closing(connect(db_path)) as connection, connection:
        row = connection.execute(
            "SELECT * FROM ai_suggestions WHERE id = ?",
            (ai_suggestion_id,),
        ).fetchone()
        return _row_to_dict(row)


def list_ai_suggestions_by_book(
    book_id: int,
    *,
    db_path: str | Path = DEFAULT_DATABASE_PATH,
) -> list[RowDict]:
    with closing(connect(db_path)) as connection, connection:
        rows = connection.execute(
            """
            SELECT * FROM ai_suggestions
            WHERE book_id = ?
            ORDER BY id
            """,
            (book_id,),
        ).fetchall()
        return [_row_to_dict_required(row) for row in rows]


def list_latest_ai_suggestion_by_book(
    book_id: int,
    *,
    db_path: str | Path = DEFAULT_DATABASE_PATH,
) -> RowDict | None:
    with closing(connect(db_path)) as connection, connection:
        row = connection.execute(
            """
            SELECT * FROM ai_suggestions
            WHERE book_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (book_id,),
        ).fetchone()
        return _row_to_dict(row)


def delete_ai_suggestions_by_book(
    book_id: int,
    *,
    db_path: str | Path = DEFAULT_DATABASE_PATH,
) -> int:
    with closing(connect(db_path)) as connection, connection:
        cursor = connection.execute(
            "DELETE FROM ai_suggestions WHERE book_id = ?",
            (book_id,),
        )
        return cursor.rowcount


def delete_all_ai_suggestions(
    *,
    db_path: str | Path = DEFAULT_DATABASE_PATH,
) -> int:
    with closing(connect(db_path)) as connection, connection:
        cursor = connection.execute("DELETE FROM ai_suggestions")
        return cursor.rowcount


def create_metadata_search_result(
    *,
    book_id: int,
    provider: str = "",
    query_snapshot: Any = "{}",
    diagnostics_json: Any = "{}",
    candidates_json: Any = "[]",
    status: str = "completed",
    error_message: str = "",
    db_path: str | Path = DEFAULT_DATABASE_PATH,
) -> RowDict:
    timestamp = _now()
    with closing(connect(db_path)) as connection, connection:
        cursor = connection.execute(
            """
            INSERT INTO metadata_search_results (
              book_id, provider, query_snapshot, diagnostics_json,
              candidates_json, status, error_message, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (book_id, provider, _json_text(query_snapshot), _json_text(diagnostics_json),
             _json_text(candidates_json), status, error_message, timestamp, timestamp),
        )
        return _get_required_by_id(connection, "metadata_search_results", int(cursor.lastrowid))


def get_latest_metadata_search_result_by_book(
    book_id: int,
    *,
    db_path: str | Path = DEFAULT_DATABASE_PATH,
) -> RowDict | None:
    with closing(connect(db_path)) as connection, connection:
        row = connection.execute(
            "SELECT * FROM metadata_search_results WHERE book_id = ? ORDER BY id DESC LIMIT 1",
            (book_id,),
        ).fetchone()
        return _row_to_dict(row)


def list_metadata_search_results_by_book(
    book_id: int,
    *,
    db_path: str | Path = DEFAULT_DATABASE_PATH,
    limit: int = 50,
) -> list[RowDict]:
    with closing(connect(db_path)) as connection, connection:
        rows = connection.execute(
            """
            SELECT * FROM metadata_search_results
            WHERE book_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (book_id, limit),
        ).fetchall()
        return [_row_to_dict_required(row) for row in rows]


def delete_metadata_search_results_by_book(
    book_id: int,
    *,
    db_path: str | Path = DEFAULT_DATABASE_PATH,
) -> int:
    with closing(connect(db_path)) as connection, connection:
        cursor = connection.execute(
            "DELETE FROM metadata_search_results WHERE book_id = ?",
            (book_id,),
        )
        return cursor.rowcount


def delete_all_metadata_search_results(
    *,
    db_path: str | Path = DEFAULT_DATABASE_PATH,
) -> int:
    with closing(connect(db_path)) as connection, connection:
        cursor = connection.execute("DELETE FROM metadata_search_results")
        return cursor.rowcount


def create_ai_request_log(
    *,
    book_id: int | None,
    task_id: str,
    request_type: str,
    provider: str,
    model: str = "",
    request_json: Any = "{}",
    response_text: str = "",
    parsed_json: Any = "{}",
    status: str = "",
    error_message: str = "",
    duration_ms: int = 0,
    db_path: str | Path = DEFAULT_DATABASE_PATH,
) -> RowDict:
    timestamp = _now()
    with closing(connect(db_path)) as connection, connection:
        cursor = connection.execute(
            """
            INSERT INTO ai_request_logs (
              book_id, task_id, request_type, provider, model,
              request_json, response_text, parsed_json,
              status, error_message, duration_ms, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (book_id, task_id, request_type, provider, model,
             _json_text(request_json), response_text[:20000], _json_text(parsed_json),
             status, error_message, duration_ms, timestamp),
        )
        return _get_required_by_id(connection, "ai_request_logs", int(cursor.lastrowid))


def list_ai_request_logs_by_book(
    book_id: int,
    *,
    db_path: str | Path = DEFAULT_DATABASE_PATH,
    limit: int = 50,
) -> list[RowDict]:
    with closing(connect(db_path)) as connection, connection:
        rows = connection.execute(
            "SELECT * FROM ai_request_logs WHERE book_id = ? ORDER BY id DESC LIMIT ?",
            (book_id, limit),
        ).fetchall()
        return [_row_to_dict_required(r) for r in rows]


def list_ai_request_logs(
    *,
    db_path: str | Path = DEFAULT_DATABASE_PATH,
    limit: int = 100,
) -> list[RowDict]:
    with closing(connect(db_path)) as connection, connection:
        rows = connection.execute(
            "SELECT * FROM ai_request_logs ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [_row_to_dict_required(row) for row in rows]


def delete_ai_request_logs_by_book(
    book_id: int,
    *,
    db_path: str | Path = DEFAULT_DATABASE_PATH,
) -> int:
    with closing(connect(db_path)) as connection, connection:
        cursor = connection.execute(
            "DELETE FROM ai_request_logs WHERE book_id = ?",
            (book_id,),
        )
        return cursor.rowcount


def delete_all_ai_request_logs(
    *,
    db_path: str | Path = DEFAULT_DATABASE_PATH,
) -> int:
    with closing(connect(db_path)) as connection, connection:
        cursor = connection.execute("DELETE FROM ai_request_logs")
        return cursor.rowcount


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


def _clean_ids(row_ids: list[int]) -> list[int]:
    return [int(row_id) for row_id in row_ids]


def _placeholders(values: list[int]) -> str:
    return ", ".join("?" for _ in values)


def _json_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


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
