from __future__ import annotations

from app.search.query_builder import build_query_plan
from app.search.types import MetadataSearchQuery


class TestQueryBuilder:

    def test_builds_japanese_queries(self) -> None:
        query = MetadataSearchQuery(
            title="輕聲密語",
            authors=["池田學志"],
            language_iso="ja",
            local_clean_title="輕聲密語",
        )
        plan = build_query_plan(query)
        assert len(plan.jp_queries) > 0
        assert any("輕聲密語" in q for q in plan.jp_queries)
        assert any("池田學志" in q for q in plan.jp_queries)

    def test_builds_english_queries(self) -> None:
        query = MetadataSearchQuery(
            title="Berserk",
            authors=["Kentaro Miura"],
            language_iso="en",
        )
        plan = build_query_plan(query)
        assert len(plan.en_queries) > 0
        assert any("Berserk" in q for q in plan.en_queries)

    def test_builds_queries_for_cjk_title(self) -> None:
        query = MetadataSearchQuery(
            title="葬送的芙莉莲",
            language_iso="zh",
        )
        plan = build_query_plan(query)
        assert any("葬送的芙莉莲" in q for q in plan.jp_queries)

    def test_uses_original_title(self) -> None:
        query = MetadataSearchQuery(
            title="Frieren",
            original_title="葬送のフリーレン",
            language_iso="ja",
        )
        plan = build_query_plan(query)
        assert any("葬送のフリーレン" in q for q in plan.jp_queries)

    def test_clean_title_gets_priority(self) -> None:
        query = MetadataSearchQuery(
            title="[Kome] Clean Title v01",
            local_clean_title="Clean Title",
            language_iso="zh",
        )
        plan = build_query_plan(query)
        assert plan.jp_queries[0] is not None
        assert "Clean Title" in plan.jp_queries[0]

    def test_has_all_query_types(self) -> None:
        query = MetadataSearchQuery(
            title="Test",
            original_title="Original",
            authors=["Author"],
            language_iso="ja",
        )
        plan = build_query_plan(query)
        all_q = plan.all_queries()
        assert len(all_q) > 0

    def test_fallback_when_empty(self) -> None:
        query = MetadataSearchQuery(title="Only Title", language_iso="xx")
        plan = build_query_plan(query)
        assert len(plan.all_queries()) > 0
