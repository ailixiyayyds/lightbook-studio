from __future__ import annotations

import json
from pathlib import Path

from app.ai.context_builder import build_ai_metadata_request
from app.ai.openai_compatible_provider import OpenAICompatibleProvider
from app.storage import repositories


def test_ai_prompt_contains_raw_input_and_local_clean_guess(tmp_path: Path) -> None:
    db_path = tmp_path / "lightbook.db"
    work = repositories.create_work(
        title="[Kome][輕聲密語]卷04",
        summary="[Kmoe][輕聲密語] 的漫画元数据建议，共 166 页。",
        genres="漫画",
        language_iso="zh-TW",
        db_path=db_path,
    )
    book = repositories.create_book(
        work_id=int(work["id"]),
        title="[Kome][輕聲密語]卷04.cbz",
        volume_number=4,
        media_type="comic",
        source_type="cbz",
        source_path=str(tmp_path / "[Kome][輕聲密語]卷04.cbz"),
        page_count=166,
        manga_direction="rtl",
        db_path=db_path,
    )

    request = build_ai_metadata_request(int(book["id"]), _Repository(db_path))
    provider = OpenAICompatibleProvider(api_key="test-key", model="deepseek-v4-flash")
    payload = provider._build_payload(request)
    user_payload = json.loads(payload["messages"][1]["content"])
    raw_input = user_payload["raw_input"]

    assert raw_input["raw_series_title"] == "[Kome][輕聲密語]卷04"
    assert raw_input["raw_book_title"] == "[Kome][輕聲密語]卷04.cbz"
    assert raw_input["source_filename"] == "[Kome][輕聲密語]卷04.cbz"
    assert raw_input["local_clean_guess"] == {
        "clean_title": "輕聲密語",
        "book_title": "第 04 卷",
        "volume_number": 4,
    }
    assert raw_input["page_count"] == 166
    assert raw_input["chapter_titles"] == []
    assert raw_input["text_sample"] == ""
    assert "current_metadata" in user_payload["context"]


class _Repository:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def get_book(self, book_id: int) -> dict | None:
        return repositories.get_book(book_id, db_path=self.db_path)

    def get_work(self, work_id: int) -> dict | None:
        return repositories.get_work(work_id, db_path=self.db_path)

    def list_novel_chapters(self, book_id: int) -> list[dict]:
        return repositories.list_novel_chapters(book_id, db_path=self.db_path)
