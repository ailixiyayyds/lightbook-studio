from pathlib import Path


def test_ai_suggestion_table_has_no_confidence_column() -> None:
    source = Path("app/gui/main_window.py").read_text(encoding="utf-8")

    assert '["字段", "当前值", "AI 建议", "应用"]' in source
    assert '["字段", "当前值", "AI 建议", "置信度", "应用"]' not in source


def test_ai_suggestion_fields_are_chinese_and_include_main_metadata() -> None:
    source = Path("app/gui/main_window.py").read_text(encoding="utf-8")

    for label in ("作品名", "本卷标题", "作者", "简介", "分类", "标签", "语言", "阅读方向"):
        assert label in source


def test_import_buttons_are_consolidated() -> None:
    source = Path("app/gui/main_window.py").read_text(encoding="utf-8")

    assert "导入文件" in source
    assert "导入文件夹" in source
    assert "扫描目录" in source
    assert "选中项标记可导出" not in source
    assert "选中项标记待确认" not in source
    assert "删除选中项" in source


def test_internal_state_values_are_not_polluted_by_chinese() -> None:
    source = Path("app/gui/main_window.py").read_text(encoding="utf-8")

    assert "clean_title" in source
    assert "book_title" in source
    assert "volume_number" in source
    assert "manga_direction" in source
    assert "language_iso" in source

    assert "rtl" in source
    assert "ltr" in source
    assert "webtoon" in source

    assert '"zh"' in source
