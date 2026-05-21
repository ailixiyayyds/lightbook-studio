from __future__ import annotations

from pathlib import Path

import pytest

from app.ai.context_builder import MetadataContextBuilderError, build_ai_metadata_request
from app.storage import repositories


def test_build_ai_metadata_request_for_comic(tmp_path: Path) -> None:
    db_path = tmp_path / "lightbook.db"
    work = repositories.create_work(
        title="Comic Series",
        author="Author",
        summary="Summary",
        genres="Action, Fantasy",
        tags="Tag A, Tag B",
        language_iso="zh",
        db_path=db_path,
    )
    book = repositories.create_book(
        work_id=int(work["id"]),
        title="Volume 1",
        volume_number=1,
        media_type="comic",
        source_type="cbz",
        source_path=str(tmp_path / "Comic Series v01.cbz"),
        page_count=120,
        cover_path=str(tmp_path / "poster.jpg"),
        cover_override_path=str(tmp_path / "custom.jpg"),
        manga_direction="rtl",
        db_path=db_path,
    )
    repository = _Repository(db_path)

    request = build_ai_metadata_request(int(book["id"]), repository)

    assert request.book_id == book["id"]
    assert request.media_type == "comic"
    assert request.current_metadata == {
        "series_title": "Comic Series",
        "book_title": "Volume 1",
        "volume_number": 1,
        "translator": "",
        "author": "Author",
        "summary": "Summary",
        "genres": "Action, Fantasy",
        "tags": "Tag A, Tag B",
        "language_iso": "zh",
        "manga_direction": "rtl",
    }
    assert request.source_info["source_type"] == "cbz"
    assert request.source_info["source_path"] == str(tmp_path / "Comic Series v01.cbz")
    assert request.source_info["original_filename"] == "Comic Series v01.cbz"
    assert request.source_info["source_filename"] == "Comic Series v01.cbz"
    assert request.source_info["raw_series_title"] == "Comic Series"
    assert request.source_info["raw_book_title"] == "Volume 1"
    assert request.source_info["local_clean_guess"] == {
        "clean_title": "Comic Series",
        "book_title": "第 01 卷",
        "volume_number": 1,
    }
    assert request.chapter_titles == []
    assert request.text_sample == ""
    assert request.page_count == 120
    assert request.cover_path == str(tmp_path / "custom.jpg")


def test_build_ai_metadata_request_for_novel_limits_chapters_and_text(tmp_path: Path) -> None:
    db_path = tmp_path / "lightbook.db"
    work = repositories.create_work(title="Novel Series", db_path=db_path)
    book = repositories.create_book(
        work_id=int(work["id"]),
        title="First Volume",
        media_type="novel",
        source_type="novel_txt",
        source_path=str(tmp_path / "3159 gbk.txt"),
        chapter_count=100,
        text_length=12000,
        export_format="epub",
        cover_path=str(tmp_path / "imported-cover.jpg"),
        db_path=db_path,
    )
    for index in range(1, 101):
        repositories.create_novel_chapter(
            book_id=int(book["id"]),
            title=f"Chapter {index}",
            content=f"{index}-" + ("正文" * 100),
            order_index=index,
            db_path=db_path,
        )
    repository = _Repository(db_path)

    request = build_ai_metadata_request(int(book["id"]), repository)

    assert request.media_type == "novel"
    assert request.page_count is None
    assert len(request.chapter_titles) == 80
    assert request.chapter_titles[0] == "Chapter 1"
    assert request.chapter_titles[-1] == "Chapter 80"
    assert len(request.text_sample) == 5000
    assert "Chapter 100" not in request.text_sample
    assert request.cover_path == str(tmp_path / "imported-cover.jpg")
    assert request.source_info["chapter_count"] == 100


def test_build_ai_metadata_request_uses_cover_path_when_no_override(tmp_path: Path) -> None:
    db_path = tmp_path / "lightbook.db"
    work = repositories.create_work(title="Series", db_path=db_path)
    book = repositories.create_book(
        work_id=int(work["id"]),
        title="Book",
        source_type="epub",
        source_path=str(tmp_path / "book.epub"),
        cover_path=str(tmp_path / "cover.jpg"),
        db_path=db_path,
    )

    request = build_ai_metadata_request(int(book["id"]), _Repository(db_path))

    assert request.cover_path == str(tmp_path / "cover.jpg")


def test_build_ai_metadata_request_rejects_missing_book(tmp_path: Path) -> None:
    repository = _Repository(tmp_path / "lightbook.db")

    with pytest.raises(MetadataContextBuilderError, match="book 不存在"):
        build_ai_metadata_request(999, repository)


class _Repository:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def get_book(self, book_id: int) -> dict | None:
        return repositories.get_book(book_id, db_path=self.db_path)

    def get_work(self, work_id: int) -> dict | None:
        return repositories.get_work(work_id, db_path=self.db_path)

    def list_novel_chapters(self, book_id: int) -> list[dict]:
        return repositories.list_novel_chapters(book_id, db_path=self.db_path)
