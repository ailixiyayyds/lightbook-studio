from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Final

DEFAULT_DATABASE_PATH: Final[Path] = Path("data") / "lightbook.db"
SCHEMA_PATH: Final[Path] = Path(__file__).with_name("schema.sql")


def initialize_database(db_path: str | Path = DEFAULT_DATABASE_PATH) -> Path:
    database_path = Path(db_path)
    database_path.parent.mkdir(parents=True, exist_ok=True)

    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    with closing(sqlite3.connect(database_path)) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(schema)
        _migrate_database(connection)
        connection.commit()

    return database_path


def connect(db_path: str | Path = DEFAULT_DATABASE_PATH) -> sqlite3.Connection:
    database_path = initialize_database(db_path)
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _migrate_database(connection: sqlite3.Connection) -> None:
    _ensure_column(connection, "books", "media_type", "TEXT DEFAULT 'comic'")
    _ensure_column(connection, "books", "translator", "TEXT DEFAULT ''")
    _ensure_column(connection, "books", "manga_direction", "TEXT DEFAULT 'rtl'")
    _ensure_column(connection, "books", "chapter_count", "INTEGER DEFAULT 0")
    _ensure_column(connection, "books", "text_length", "INTEGER DEFAULT 0")
    _ensure_column(connection, "books", "export_format", "TEXT DEFAULT ''")
    _ensure_column(connection, "books", "cover_override_path", "TEXT DEFAULT ''")
    _ensure_novel_chapters_table(connection)
    _ensure_ai_suggestions_table(connection)
    _ensure_index(connection, "idx_books_media_type", "books", "media_type")
    _ensure_index(connection, "idx_novel_chapters_book_id", "novel_chapters", "book_id")
    _ensure_index(connection, "idx_ai_suggestions_book_id", "ai_suggestions", "book_id")
    _ensure_index(connection, "idx_ai_suggestions_status", "ai_suggestions", "status")


def _ensure_column(
    connection: sqlite3.Connection,
    table_name: str,
    column_name: str,
    column_definition: str,
) -> None:
    columns = {
        str(row[1])
        for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
    if column_name not in columns:
        connection.execute(
            f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}"
        )


def _ensure_index(
    connection: sqlite3.Connection,
    index_name: str,
    table_name: str,
    column_name: str,
) -> None:
    connection.execute(
        f"CREATE INDEX IF NOT EXISTS {index_name} ON {table_name}({column_name})"
    )


def _ensure_novel_chapters_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS novel_chapters (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          book_id INTEGER NOT NULL,
          title TEXT NOT NULL,
          content TEXT NOT NULL,
          order_index INTEGER NOT NULL,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          FOREIGN KEY(book_id) REFERENCES books(id)
        )
        """
    )


def _ensure_ai_suggestions_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_suggestions (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          book_id INTEGER NOT NULL,
          provider TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'pending',
          input_snapshot TEXT NOT NULL DEFAULT '{}',
          raw_response TEXT NOT NULL DEFAULT '',
          parsed_json TEXT NOT NULL DEFAULT '{}',
          confidence REAL DEFAULT 0,
          error_message TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          FOREIGN KEY(book_id) REFERENCES books(id)
        )
        """
    )
