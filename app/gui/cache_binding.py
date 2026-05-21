from __future__ import annotations

from typing import Any


def should_refresh_book_cache(
    *,
    expected_book_id: int,
    current_book_id: int | None,
    cached_row: dict[str, Any],
) -> bool:
    """Return True only when a cached row belongs to the selected book."""
    if current_book_id != expected_book_id:
        return False
    try:
        row_book_id = int(cached_row.get("book_id"))
    except (TypeError, ValueError):
        return False
    return row_book_id == expected_book_id
