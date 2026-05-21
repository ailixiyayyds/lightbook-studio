from __future__ import annotations

from pathlib import Path

from app.gui.cache_binding import should_refresh_book_cache
from app.storage import repositories


def test_ai_cache_is_bound_to_book_id(tmp_path: Path) -> None:
    db_path = tmp_path / "lightbook.db"
    book_a = _book(db_path, "A")
    book_b = _book(db_path, "B")
    suggestion_a = repositories.create_ai_suggestion(
        book_id=int(book_a["id"]),
        provider="mock",
        status="completed",
        parsed_json={"clean_title": "A"},
        db_path=db_path,
    )

    assert not should_refresh_book_cache(
        expected_book_id=int(book_a["id"]),
        current_book_id=int(book_b["id"]),
        cached_row=suggestion_a,
    )
    assert should_refresh_book_cache(
        expected_book_id=int(book_a["id"]),
        current_book_id=int(book_a["id"]),
        cached_row=suggestion_a,
    )


def test_search_cache_is_bound_to_book_id(tmp_path: Path) -> None:
    db_path = tmp_path / "lightbook.db"
    book_a = _book(db_path, "A")
    book_b = _book(db_path, "B")
    result_a = repositories.create_metadata_search_result(
        book_id=int(book_a["id"]),
        provider="mock",
        candidates_json=[{"title": "A"}],
        db_path=db_path,
    )

    assert not should_refresh_book_cache(
        expected_book_id=int(book_a["id"]),
        current_book_id=int(book_b["id"]),
        cached_row=result_a,
    )
    assert should_refresh_book_cache(
        expected_book_id=int(book_a["id"]),
        current_book_id=int(book_a["id"]),
        cached_row=result_a,
    )


def test_deleting_book_removes_its_caches_without_affecting_other_books(tmp_path: Path) -> None:
    db_path = tmp_path / "lightbook.db"
    book_a = _book(db_path, "A")
    book_b = _book(db_path, "B")
    repositories.create_ai_suggestion(book_id=int(book_a["id"]), provider="mock", db_path=db_path)
    repositories.create_metadata_search_result(book_id=int(book_a["id"]), provider="mock", db_path=db_path)
    repositories.create_ai_suggestion(book_id=int(book_b["id"]), provider="mock", db_path=db_path)
    repositories.create_metadata_search_result(book_id=int(book_b["id"]), provider="mock", db_path=db_path)

    repositories.delete_books([int(book_a["id"])], db_path=db_path)

    assert repositories.list_latest_ai_suggestion_by_book(int(book_a["id"]), db_path=db_path) is None
    assert repositories.get_latest_metadata_search_result_by_book(int(book_a["id"]), db_path=db_path) is None
    assert repositories.list_latest_ai_suggestion_by_book(int(book_b["id"]), db_path=db_path) is not None
    assert repositories.get_latest_metadata_search_result_by_book(int(book_b["id"]), db_path=db_path) is not None


def _book(db_path: Path, title: str) -> dict:
    work = repositories.create_work(title=title, db_path=db_path)
    return repositories.create_book(
        work_id=int(work["id"]),
        title=title,
        source_type="cbz",
        source_path=f"{title}.cbz",
        db_path=db_path,
    )
