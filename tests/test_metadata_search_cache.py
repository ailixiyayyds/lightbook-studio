from __future__ import annotations

import json
from pathlib import Path

from app.search.types import MetadataSearchCandidate
from app.search.web_search_service import MetadataSearchService
from app.storage import repositories


def test_metadata_search_result_is_saved_and_loaded_by_book(tmp_path: Path) -> None:
    db_path = tmp_path / "lightbook.db"
    book = _book(db_path, "Title")
    row = repositories.create_metadata_search_result(
        book_id=int(book["id"]),
        provider="mock",
        query_snapshot={"title": "Title"},
        diagnostics_json={"providers": [{"name": "mock", "candidate_count": 1}]},
        candidates_json=[{"title": "Title", "source_name": "Mock"}],
        status="completed",
        db_path=db_path,
    )

    latest = repositories.get_latest_metadata_search_result_by_book(int(book["id"]), db_path=db_path)
    assert latest is not None
    assert latest["id"] == row["id"]
    assert json.loads(str(latest["query_snapshot"]))["title"] == "Title"
    assert json.loads(str(latest["diagnostics_json"]))["providers"][0]["name"] == "mock"
    assert json.loads(str(latest["candidates_json"]))[0]["title"] == "Title"


def test_metadata_search_failed_result_is_cached(tmp_path: Path) -> None:
    db_path = tmp_path / "lightbook.db"
    book = _book(db_path, "Title")
    repositories.create_metadata_search_result(
        book_id=int(book["id"]),
        provider="mock",
        status="failed",
        error_message="network down",
        diagnostics_json={"duration_ms": 12},
        db_path=db_path,
    )

    latest = repositories.get_latest_metadata_search_result_by_book(int(book["id"]), db_path=db_path)
    assert latest is not None
    assert latest["status"] == "failed"
    assert latest["error_message"] == "network down"
    assert json.loads(str(latest["diagnostics_json"]))["duration_ms"] == 12


def test_apply_candidate_does_not_clear_search_cache(tmp_path: Path) -> None:
    db_path = tmp_path / "lightbook.db"
    book = _book(db_path, "Old")
    repositories.create_metadata_search_result(
        book_id=int(book["id"]),
        provider="mock",
        candidates_json=[{"title": "New"}],
        db_path=db_path,
    )
    service = MetadataSearchService(_Repository(db_path), _NoopProvider())

    service.apply_candidate(
        int(book["id"]),
        MetadataSearchCandidate(title="New", authors=["Author"]),
        ["title", "authors"],
    )

    latest = repositories.get_latest_metadata_search_result_by_book(int(book["id"]), db_path=db_path)
    assert latest is not None
    assert json.loads(str(latest["candidates_json"]))[0]["title"] == "New"


def _book(db_path: Path, title: str) -> dict:
    work = repositories.create_work(title=title, db_path=db_path)
    return repositories.create_book(
        work_id=int(work["id"]),
        title=title,
        source_type="cbz",
        source_path=f"{title}.cbz",
        db_path=db_path,
    )


class _Repository:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def get_book(self, book_id: int) -> dict | None:
        return repositories.get_book(book_id, db_path=self.db_path)

    def get_work(self, work_id: int) -> dict | None:
        return repositories.get_work(work_id, db_path=self.db_path)

    def update_work(self, work_id: int, **kwargs: object) -> dict | None:
        return repositories.update_work(work_id, **kwargs, db_path=self.db_path)

    def update_book(self, book_id: int, **kwargs: object) -> dict | None:
        return repositories.update_book(book_id, **kwargs, db_path=self.db_path)


class _NoopProvider:
    name = "noop"

    def search(self, query: object) -> list[MetadataSearchCandidate]:
        return []
