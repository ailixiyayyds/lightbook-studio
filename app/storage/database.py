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
    _ensure_column(connection, "books", "translator", "TEXT DEFAULT ''")
    _ensure_column(connection, "books", "manga_direction", "TEXT DEFAULT 'rtl'")


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
