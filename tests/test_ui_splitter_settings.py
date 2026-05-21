from pathlib import Path

from app.storage import repositories


def test_splitter_sizes_can_be_saved_and_loaded_from_settings(tmp_path: Path) -> None:
    db_path = tmp_path / "lightbook.db"
    repositories.set_setting("ui_main_splitter_sizes", "[765, 935]", db_path=db_path)
    repositories.set_setting("ui_chapter_splitter_sizes", "[360, 300]", db_path=db_path)
    repositories.set_setting("ui_cover_search_splitter_sizes", "[300, 520]", db_path=db_path)
    repositories.set_setting("ui_detail_current_tab", "0", db_path=db_path)

    assert repositories.get_setting("ui_main_splitter_sizes", db_path=db_path) == "[765, 935]"
    assert repositories.get_setting("ui_chapter_splitter_sizes", db_path=db_path) == "[360, 300]"
    assert repositories.get_setting("ui_cover_search_splitter_sizes", db_path=db_path) == "[300, 520]"
    assert repositories.get_setting("ui_detail_current_tab", db_path=db_path) == "0"


def test_main_window_contains_horizontal_and_vertical_splitters() -> None:
    source = Path("app/gui/main_window.py").read_text(encoding="utf-8")

    assert "ui_main_splitter_sizes" in source
    assert "ui_chapter_splitter_sizes" in source
    assert "ui_cover_search_splitter_sizes" in source
    assert "ui_detail_current_tab" in source
    assert "QSplitter(Qt.Orientation.Horizontal)" in source
    assert "QSplitter(Qt.Orientation.Vertical)" in source


def test_detail_tabs_structure() -> None:
    source = Path("app/gui/main_window.py").read_text(encoding="utf-8")

    assert "self.detail_tabs = QTabWidget()" in source
    assert 'self.detail_tabs.addTab(self._build_basic_info_tab(), "基本信息")' in source
    assert 'self.detail_tabs.addTab(self._build_chapter_tab(), "章节 / 正文")' in source
    assert 'self.detail_tabs.addTab(self._build_ai_tab(), "AI 建议")' in source
    assert 'self.detail_tabs.addTab(self._build_cover_search_tab(), "封面 / 资料搜索")' in source
    assert 'self.detail_tabs.addTab(self._build_export_cache_tab(), "导出 / 缓存")' in source
    assert "self.chapter_splitter.setChildrenCollapsible(False)" in source
    assert "self.cover_search_splitter.setChildrenCollapsible(False)" in source
    assert "self.batch_cover_preview_label.setMinimumSize(260, 360)" in source
    assert "self.batch_chapter_table.setMinimumHeight(300)" in source
    assert "self.batch_chapter_preview_edit.setMinimumHeight(240)" in source
    assert "self.ai_suggestion_table.setMinimumHeight(420)" in source
    assert "self.chapter_stack = QStackedWidget()" in source
