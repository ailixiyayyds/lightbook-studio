from pathlib import Path

from app.core.cache_cleanup import cleanup_old_log_files, cleanup_unreferenced_cover_cache
from app.storage import repositories


def test_cleanup_ai_and_search_caches(tmp_path: Path) -> None:
    db_path = tmp_path / "lightbook.db"
    book = _book(db_path)
    repositories.create_ai_suggestion(book_id=int(book["id"]), provider="mock", db_path=db_path)
    repositories.create_metadata_search_result(book_id=int(book["id"]), provider="mock", db_path=db_path)

    assert repositories.delete_ai_suggestions_by_book(int(book["id"]), db_path=db_path) == 1
    assert repositories.delete_metadata_search_results_by_book(int(book["id"]), db_path=db_path) == 1
    assert repositories.list_latest_ai_suggestion_by_book(int(book["id"]), db_path=db_path) is None
    assert repositories.get_latest_metadata_search_result_by_book(int(book["id"]), db_path=db_path) is None


def test_cleanup_ai_request_logs(tmp_path: Path) -> None:
    db_path = tmp_path / "lightbook.db"
    book = _book(db_path)
    repositories.create_ai_request_log(
        book_id=int(book["id"]),
        task_id="t",
        request_type="metadata_suggestion",
        provider="mock",
        status="completed",
        db_path=db_path,
    )

    assert repositories.delete_ai_request_logs_by_book(int(book["id"]), db_path=db_path) == 1
    assert repositories.list_ai_request_logs_by_book(int(book["id"]), db_path=db_path) == []


def test_delete_all_cache_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "lightbook.db"
    book = _book(db_path)
    repositories.create_ai_suggestion(book_id=int(book["id"]), provider="mock", db_path=db_path)
    repositories.create_metadata_search_result(book_id=int(book["id"]), provider="mock", db_path=db_path)
    repositories.create_ai_request_log(
        book_id=int(book["id"]),
        task_id="t",
        request_type="metadata_suggestion",
        provider="mock",
        status="completed",
        db_path=db_path,
    )

    assert repositories.delete_all_ai_suggestions(db_path=db_path) == 1
    assert repositories.delete_all_metadata_search_results(db_path=db_path) == 1
    assert repositories.delete_all_ai_request_logs(db_path=db_path) == 1


def test_cleanup_unreferenced_cover_cache_keeps_referenced_files(tmp_path: Path) -> None:
    covers_root = tmp_path / "data" / "covers"
    covers_root.mkdir(parents=True)
    referenced = covers_root / "keep.jpg"
    unreferenced = covers_root / "remove.jpg"
    nested = covers_root / "nested" / "remove-too.jpg"
    nested.parent.mkdir()
    referenced.write_bytes(b"keep")
    unreferenced.write_bytes(b"remove")
    nested.write_bytes(b"remove")

    count = cleanup_unreferenced_cover_cache(covers_root, {referenced})

    assert count == 2
    assert referenced.exists()
    assert not unreferenced.exists()
    assert not nested.exists()


def test_cleanup_old_log_files_keeps_current_log(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    current = log_dir / "lightbook.log"
    old_1 = log_dir / "lightbook.log.1"
    old_2 = log_dir / "lightbook.log.2"
    unrelated = log_dir / "other.log.1"
    current.write_text("current", encoding="utf-8")
    old_1.write_text("old", encoding="utf-8")
    old_2.write_text("old", encoding="utf-8")
    unrelated.write_text("keep", encoding="utf-8")

    count = cleanup_old_log_files(log_dir, current)

    assert count == 2
    assert current.exists()
    assert unrelated.exists()
    assert not old_1.exists()
    assert not old_2.exists()


def _book(db_path: Path) -> dict:
    work = repositories.create_work(title="Series", db_path=db_path)
    return repositories.create_book(
        work_id=int(work["id"]),
        title="Book",
        source_type="cbz",
        source_path="Book.cbz",
        db_path=db_path,
    )
