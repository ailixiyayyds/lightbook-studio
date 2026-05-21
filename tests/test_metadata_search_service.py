from __future__ import annotations

from pathlib import Path
from typing import Any

from app.search.mock_search_provider import MockSearchProvider
from app.search.provider import BaseMetadataSearchProvider
from app.search.types import MetadataSearchCandidate, MetadataSearchQuery
from app.search.web_search_service import (
    MetadataSearchService,
    MetadataSearchServiceError,
    download_cover,
)
from app.storage import repositories


def test_mock_search_provider_returns_candidates() -> None:
    provider = MockSearchProvider()
    query = MetadataSearchQuery(
        title="輕聲密語",
        authors=["池田學志"],
        media_type="comic",
        language_iso="zh-TW",
    )

    candidates = provider.search(query)

    assert len(candidates) >= 1
    first = candidates[0]
    assert first.title == "輕聲密語"
    assert first.authors == ["池田學志"]
    assert first.source_name == "Mock 资料库"
    assert first.cover_url.startswith("mock://cover/")
    assert len(first.genres) >= 1
    assert len(first.tags) >= 1


def test_mock_search_provider_returns_two_candidates_for_long_title() -> None:
    provider = MockSearchProvider()
    query = MetadataSearchQuery(title="長篇作品名稱", media_type="comic")

    candidates = provider.search(query)

    assert len(candidates) == 2
    assert candidates[0].source_name != candidates[1].source_name


def test_mock_search_provider_returns_empty_for_blank_title() -> None:
    provider = MockSearchProvider()
    query = MetadataSearchQuery(title="", media_type="comic")

    candidates = provider.search(query)

    assert candidates == []


def test_mock_search_provider_novel_type() -> None:
    provider = MockSearchProvider()
    query = MetadataSearchQuery(title="测试轻小说", media_type="novel")

    candidates = provider.search(query)

    assert len(candidates) >= 1
    assert "轻小说" in candidates[0].genres
    assert "轻小说" in candidates[0].summary


def test_search_for_book_returns_candidates(tmp_path: Path) -> None:
    db_path = tmp_path / "lightbook.db"
    work = repositories.create_work(
        title="Test Series",
        author="Test Author",
        language_iso="zh",
        db_path=db_path,
    )
    book = repositories.create_book(
        work_id=int(work["id"]),
        title="Book 1",
        source_type="cbz",
        source_path=str(tmp_path / "test.cbz"),
        db_path=db_path,
    )
    repository = _Repository(db_path)
    service = MetadataSearchService(repository, MockSearchProvider(), data_dir=tmp_path / "data")

    candidates = service.search_for_book(int(book["id"]))

    assert len(candidates) >= 1
    assert candidates[0].title == "Test Series"
    assert candidates[0].authors == ["Test Author"]


def test_search_for_book_empty_title_returns_empty(tmp_path: Path) -> None:
    db_path = tmp_path / "lightbook.db"
    work = repositories.create_work(title="", db_path=db_path)
    book = repositories.create_book(
        work_id=int(work["id"]),
        title="",
        source_type="cbz",
        source_path=str(tmp_path / "test.cbz"),
        db_path=db_path,
    )
    repository = _Repository(db_path)
    service = MetadataSearchService(repository, MockSearchProvider(), data_dir=tmp_path / "data")

    candidates = service.search_for_book(int(book["id"]))

    assert candidates == []


def test_apply_candidate_only_updates_selected_fields(tmp_path: Path) -> None:
    db_path = tmp_path / "lightbook.db"
    work = repositories.create_work(
        title="Original Title",
        author="Original Author",
        summary="Original summary",
        genres="old-genre",
        tags="old-tag",
        db_path=db_path,
    )
    book = repositories.create_book(
        work_id=int(work["id"]),
        title="Original Book",
        source_type="cbz",
        source_path=str(tmp_path / "test.cbz"),
        db_path=db_path,
    )
    repository = _Repository(db_path)
    service = MetadataSearchService(repository, MockSearchProvider(), data_dir=tmp_path / "data")

    candidate = MetadataSearchCandidate(
        title="New Title",
        authors=["New Author"],
        summary="New summary",
        genres=["Drama", "Fantasy"],
        tags=["Magic", "School"],
        source_name="Test",
        source_url="mock://test",
    )

    service.apply_candidate(int(book["id"]), candidate, ["title", "authors", "tags"])

    updated_work = repositories.get_work(int(work["id"]), db_path=db_path)
    updated_book = repositories.get_book(int(book["id"]), db_path=db_path)
    assert updated_work is not None
    assert updated_book is not None
    assert updated_work["title"] == "New Title"
    assert updated_work["author"] == "New Author"
    assert updated_work["tags"] == "Magic, School"
    assert updated_work["summary"] == "Original summary"
    assert updated_work["genres"] == "old-genre"
    assert updated_book["title"] == "Original Book"


def test_apply_candidate_with_empty_fields_does_not_modify(tmp_path: Path) -> None:
    db_path = tmp_path / "lightbook.db"
    work = repositories.create_work(title="Keep Title", author="Keep Author", db_path=db_path)
    book = repositories.create_book(
        work_id=int(work["id"]),
        title="Keep Book",
        source_type="cbz",
        source_path=str(tmp_path / "test.cbz"),
        db_path=db_path,
    )
    repository = _Repository(db_path)
    service = MetadataSearchService(repository, MockSearchProvider(), data_dir=tmp_path / "data")

    candidate = MetadataSearchCandidate(
        title="New Title",
        authors=["New Author"],
        source_name="Test",
        source_url="mock://test",
    )

    service.apply_candidate(int(book["id"]), candidate, [])

    unchanged_work = repositories.get_work(int(work["id"]), db_path=db_path)
    assert unchanged_work is not None
    assert unchanged_work["title"] == "Keep Title"
    assert unchanged_work["author"] == "Keep Author"


def test_apply_candidate_cover_is_not_downloaded_when_not_selected(tmp_path: Path) -> None:
    db_path = tmp_path / "lightbook.db"
    work = repositories.create_work(title="Series", db_path=db_path)
    book = repositories.create_book(
        work_id=int(work["id"]),
        title="Book",
        source_type="cbz",
        source_path=str(tmp_path / "test.cbz"),
        cover_override_path="",
        db_path=db_path,
    )
    repository = _Repository(db_path)
    service = MetadataSearchService(repository, MockSearchProvider(), data_dir=tmp_path / "data")

    candidate = MetadataSearchCandidate(
        title="Series",
        cover_url="mock://cover/abc/primary.jpg",
        source_name="Test",
        source_url="mock://test",
    )

    service.apply_candidate(int(book["id"]), candidate, ["title"])

    updated_book = repositories.get_book(int(book["id"]), db_path=db_path)
    assert updated_book is not None
    assert updated_book["cover_override_path"] == ""


def test_apply_candidate_downloads_cover_when_selected(tmp_path: Path) -> None:
    db_path = tmp_path / "lightbook.db"
    covers_dir = tmp_path / "data" / "covers"
    work = repositories.create_work(title="Series", db_path=db_path)
    book = repositories.create_book(
        work_id=int(work["id"]),
        title="Book",
        source_type="cbz",
        source_path=str(tmp_path / "test.cbz"),
        cover_override_path="",
        db_path=db_path,
    )
    repository = _Repository(db_path)
    service = MetadataSearchService(repository, MockSearchProvider(), data_dir=tmp_path / "data")

    candidate = MetadataSearchCandidate(
        title="Series",
        cover_url="mock://cover/abc/primary.jpg",
        source_name="Mock 资料库",
        source_url="mock://source/abc",
        tags=["comic"],
        genres=["漫画"],
    )

    service.apply_candidate(int(book["id"]), candidate, ["cover_url"])

    updated_book = repositories.get_book(int(book["id"]), db_path=db_path)
    assert updated_book is not None
    override_path = str(updated_book["cover_override_path"])
    assert "search_cover" in override_path
    assert Path(override_path).exists()
    assert str(book["id"]) in override_path


def test_apply_candidate_cover_url_requires_download(tmp_path: Path) -> None:
    db_path = tmp_path / "lightbook.db"
    work = repositories.create_work(title="Series", db_path=db_path)
    book = repositories.create_book(
        work_id=int(work["id"]),
        title="Book",
        source_type="cbz",
        source_path=str(tmp_path / "test.cbz"),
        db_path=db_path,
    )
    repository = _Repository(db_path)
    service = MetadataSearchService(repository, MockSearchProvider(), data_dir=tmp_path / "data")

    candidate = MetadataSearchCandidate(
        title="Series",
        cover_url="",
        source_name="Test",
        source_url="mock://test",
    )

    service.apply_candidate(int(book["id"]), candidate, ["cover_url"])

    updated_book = repositories.get_book(int(book["id"]), db_path=db_path)
    assert updated_book is not None
    assert str(updated_book["cover_override_path"]) == ""


def test_apply_candidate_applies_summary(tmp_path: Path) -> None:
    db_path = tmp_path / "lightbook.db"
    work = repositories.create_work(title="Series", summary="Old", db_path=db_path)
    book = repositories.create_book(
        work_id=int(work["id"]),
        title="Book",
        source_type="cbz",
        source_path=str(tmp_path / "test.cbz"),
        db_path=db_path,
    )
    repository = _Repository(db_path)
    service = MetadataSearchService(repository, MockSearchProvider(), data_dir=tmp_path / "data")

    candidate = MetadataSearchCandidate(
        title="Series",
        summary="New story summary",
        source_name="Test",
        source_url="mock://test",
    )

    service.apply_candidate(int(book["id"]), candidate, ["summary"])

    updated_work = repositories.get_work(int(work["id"]), db_path=db_path)
    assert updated_work is not None
    assert updated_work["summary"] == "New story summary"


def test_apply_candidate_preserves_source_info(tmp_path: Path) -> None:
    db_path = tmp_path / "lightbook.db"
    work = repositories.create_work(title="Series", db_path=db_path)
    book = repositories.create_book(
        work_id=int(work["id"]),
        title="Book",
        source_type="cbz",
        source_path=str(tmp_path / "test.cbz"),
        db_path=db_path,
    )
    repository = _Repository(db_path)
    service = MetadataSearchService(repository, MockSearchProvider(), data_dir=tmp_path / "data")

    candidate = MetadataSearchCandidate(
        title="Series",
        source_name="Mock 资料库",
        source_url="mock://source/abc123",
        tags=["comic"],
        genres=["漫画"],
    )

    service.apply_candidate(int(book["id"]), candidate, ["tags", "genres"])

    updated_work = repositories.get_work(int(work["id"]), db_path=db_path)
    assert updated_work is not None
    assert updated_work["tags"] == "comic"
    assert updated_work["genres"] == "漫画"


def test_apply_candidate_applies_only_first_author(tmp_path: Path) -> None:
    db_path = tmp_path / "lightbook.db"
    work = repositories.create_work(title="Series", author="Old Author", db_path=db_path)
    book = repositories.create_book(
        work_id=int(work["id"]),
        title="Book",
        source_type="cbz",
        source_path=str(tmp_path / "test.cbz"),
        db_path=db_path,
    )
    repository = _Repository(db_path)
    service = MetadataSearchService(repository, MockSearchProvider(), data_dir=tmp_path / "data")

    candidate = MetadataSearchCandidate(
        title="Series",
        authors=["Primary Author", "Secondary Author"],
        source_name="Test",
        source_url="mock://test",
    )

    service.apply_candidate(int(book["id"]), candidate, ["authors"])

    updated_work = repositories.get_work(int(work["id"]), db_path=db_path)
    assert updated_work is not None
    assert updated_work["author"] == "Primary Author"


def test_search_service_rejects_missing_book(tmp_path: Path) -> None:
    db_path = tmp_path / "lightbook.db"
    repository = _Repository(db_path)
    service = MetadataSearchService(repository, MockSearchProvider(), data_dir=tmp_path / "data")

    try:
        service.search_for_book(999)
    except MetadataSearchServiceError as e:
        assert "book 不存在" in str(e)


def test_apply_candidate_rejects_missing_book(tmp_path: Path) -> None:
    db_path = tmp_path / "lightbook.db"
    repository = _Repository(db_path)
    service = MetadataSearchService(repository, MockSearchProvider(), data_dir=tmp_path / "data")

    candidate = MetadataSearchCandidate(title="X", source_name="T", source_url="mock://t")
    try:
        service.apply_candidate(999, candidate, ["title"])
    except MetadataSearchServiceError as e:
        assert "book 不存在" in str(e)


def test_download_cover_writes_file(tmp_path: Path) -> None:
    target = tmp_path / "cover.jpg"

    result = download_cover("mock://cover/test123/primary.jpg", target)

    assert result == target
    assert target.exists()
    assert target.stat().st_size > 0


def test_download_cover_rejects_non_http_for_real_urls(tmp_path: Path) -> None:
    target = tmp_path / "cover.jpg"

    try:
        download_cover("ftp://evil.com/cover.jpg", target)
    except MetadataSearchServiceError as e:
        assert "不支持的封面 URL 协议" in str(e)


def test_mock_search_does_not_leak_sensitive_data() -> None:
    provider = MockSearchProvider()
    query = MetadataSearchQuery(
        title="Test Title",
        authors=["Author Name"],
        media_type="comic",
        language_iso="zh",
    )

    candidates = provider.search(query)

    for candidate in candidates:
        serialized = str(candidate)
        assert "api_key" not in serialized.casefold()
        assert "token" not in serialized.casefold()
        assert "password" not in serialized.casefold()
        assert "secret" not in serialized.casefold()


def test_mock_search_candidate_has_source_metadata() -> None:
    provider = MockSearchProvider()
    query = MetadataSearchQuery(title="Test", media_type="comic")

    candidates = provider.search(query)

    for candidate in candidates:
        assert candidate.source_name
        assert candidate.source_url
        assert candidate.cover_url


class _Repository:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def get_book(self, book_id: int) -> dict[str, Any] | None:
        return repositories.get_book(book_id, db_path=self.db_path)

    def get_work(self, work_id: int) -> dict[str, Any] | None:
        return repositories.get_work(work_id, db_path=self.db_path)

    def update_work(self, work_id: int, **kwargs: Any) -> dict[str, Any] | None:
        return repositories.update_work(work_id, **kwargs, db_path=self.db_path)

    def update_book(self, book_id: int, **kwargs: Any) -> dict[str, Any] | None:
        return repositories.update_book(book_id, **kwargs, db_path=self.db_path)
