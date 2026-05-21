from __future__ import annotations

import json
from pathlib import Path

from app.ai.context_builder import build_ai_metadata_request
from app.ai.openai_compatible_provider import (
    AI_METADATA_SCHEMA_EXAMPLE,
    SYSTEM_PROMPT,
    OpenAICompatibleProvider,
)
from app.ai.types import AiMetadataRequest
from app.storage import repositories


def test_system_prompt_forbids_boilerplate_summaries() -> None:
    assert "这是第 N 卷" in SYSTEM_PROMPT
    assert "共 N 页" in SYSTEM_PROMPT
    assert "元数据建议" in SYSTEM_PROMPT
    assert "故事简介" in SYSTEM_PROMPT


def test_system_prompt_distinguishes_genres_and_tags() -> None:
    assert "genres 和 tags 的区别" in SYSTEM_PROMPT
    assert "genres 回答" in SYSTEM_PROMPT
    assert "tags 回答" in SYSTEM_PROMPT
    assert "两者内容不应重复" in SYSTEM_PROMPT


def test_system_prompt_defines_genres_scope() -> None:
    assert "大分类" in SYSTEM_PROMPT
    assert "漫画" in SYSTEM_PROMPT
    assert "轻小说" in SYSTEM_PROMPT
    assert "百合" in SYSTEM_PROMPT


def test_system_prompt_defines_tags_examples() -> None:
    assert "具体元素" in SYSTEM_PROMPT
    assert "暗恋" in SYSTEM_PROMPT
    assert "社团" in SYSTEM_PROMPT


def test_system_prompt_forbids_author_language_as_tags() -> None:
    assert "不要把作者、语言、页数、卷号当成 tag" in SYSTEM_PROMPT


def test_user_payload_includes_genres_vs_tags_guidance() -> None:
    provider = OpenAICompatibleProvider(api_key="test-key", model="deepseek-v4-flash")
    request = AiMetadataRequest(
        book_id=1,
        media_type="comic",
        source_info={"raw_series_title": "Test Series"},
    )
    payload = provider._build_payload(request)
    user_content = json.loads(payload["messages"][1]["content"])

    assert "genres_vs_tags" in user_content
    assert "genres_definition" in user_content["genres_vs_tags"]
    assert "tags_definition" in user_content["genres_vs_tags"]
    assert "no_overlap" in user_content["genres_vs_tags"]
    assert "not_tags" in user_content["genres_vs_tags"]


def test_user_payload_includes_summary_rules() -> None:
    provider = OpenAICompatibleProvider(api_key="test-key", model="deepseek-v4-flash")
    request = AiMetadataRequest(
        book_id=1,
        media_type="comic",
        source_info={"raw_series_title": "Test Series"},
    )
    payload = provider._build_payload(request)
    user_content = json.loads(payload["messages"][1]["content"])

    assert "summary_rule" in user_content
    assert "故事简介" in user_content["summary_rule"]["priority"]
    assert "forbidden" in user_content["summary_rule"]


def test_user_payload_includes_search_candidates_field() -> None:
    provider = OpenAICompatibleProvider(api_key="test-key", model="deepseek-v4-flash")
    request = AiMetadataRequest(
        book_id=1,
        media_type="comic",
        source_info={"raw_series_title": "Test Series", "search_candidates": []},
    )
    payload = provider._build_payload(request)
    user_content = json.loads(payload["messages"][1]["content"])

    assert "search_candidates" in user_content["raw_input"]


def test_user_payload_includes_local_clean_guess() -> None:
    provider = OpenAICompatibleProvider(api_key="test-key", model="deepseek-v4-flash")
    request = AiMetadataRequest(
        book_id=1,
        media_type="comic",
        source_info={
            "raw_series_title": "[Kome][輕聲密語]卷04",
            "local_clean_guess": {
                "clean_title": "輕聲密語",
                "book_title": "第 04 卷",
                "volume_number": 4,
            },
        },
    )
    payload = provider._build_payload(request)
    user_content = json.loads(payload["messages"][1]["content"])

    guess = user_content["raw_input"]["local_clean_guess"]
    assert guess["clean_title"] == "輕聲密語"
    assert guess["book_title"] == "第 04 卷"
    assert guess["volume_number"] == 4


def test_user_payload_includes_chapter_titles_and_text_sample() -> None:
    provider = OpenAICompatibleProvider(api_key="test-key", model="deepseek-v4-flash")
    request = AiMetadataRequest(
        book_id=1,
        media_type="novel",
        source_info={"raw_series_title": "Novel Series"},
        chapter_titles=["Chapter 1", "Chapter 2", "Chapter 3"],
        text_sample="Once upon a time in a distant land...",
        page_count=None,
    )
    payload = provider._build_payload(request)
    user_content = json.loads(payload["messages"][1]["content"])

    assert user_content["raw_input"]["chapter_titles"] == ["Chapter 1", "Chapter 2", "Chapter 3"]
    assert "Once upon a time" in user_content["raw_input"]["text_sample"]


def test_schema_example_has_all_required_fields() -> None:
    required_fields = {
        "clean_title",
        "original_title",
        "aliases",
        "book_title",
        "volume_number",
        "authors",
        "illustrators",
        "translators",
        "language_iso",
        "summary",
        "genres",
        "tags",
        "content_warnings",
        "manga_direction",
        "series_status",
        "confidence",
        "field_confidence",
        "notes",
    }
    assert set(AI_METADATA_SCHEMA_EXAMPLE.keys()) == required_fields


def test_context_builder_includes_search_candidates(tmp_path: Path) -> None:
    db_path = tmp_path / "lightbook.db"
    work = repositories.create_work(title="Test Series", db_path=db_path)
    book = repositories.create_book(
        work_id=int(work["id"]),
        title="Book 1",
        source_type="cbz",
        source_path=str(tmp_path / "test.cbz"),
        db_path=db_path,
    )
    repository = _Repository(db_path)

    request = build_ai_metadata_request(int(book["id"]), repository)

    assert "search_candidates" in request.source_info
    assert request.source_info["search_candidates"] == []


class _Repository:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def get_book(self, book_id: int) -> dict | None:
        return repositories.get_book(book_id, db_path=self.db_path)

    def get_work(self, work_id: int) -> dict | None:
        return repositories.get_work(work_id, db_path=self.db_path)

    def list_novel_chapters(self, book_id: int) -> list[dict]:
        return repositories.list_novel_chapters(book_id, db_path=self.db_path)
