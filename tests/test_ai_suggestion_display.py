from pathlib import Path


def test_ai_suggestion_table_has_no_confidence_column() -> None:
    source = Path("app/gui/main_window.py").read_text(encoding="utf-8")

    assert '["字段", "当前值", "AI 建议", "应用"]' in source
    assert '["字段", "当前值", "AI 建议", "置信度", "应用"]' not in source


def test_ai_suggestion_fields_are_chinese_and_include_main_metadata() -> None:
    source = Path("app/gui/main_window.py").read_text(encoding="utf-8")

    for label in ("作品名", "本卷标题", "作者", "简介", "分类", "标签", "语言", "阅读方向"):
        assert label in source
