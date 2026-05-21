from pathlib import Path


def test_batch_table_uses_extended_row_selection() -> None:
    source = Path("app/gui/main_window.py").read_text(encoding="utf-8")

    assert "setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)" in source
    assert "setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)" in source
    assert "QKeySequence.StandardKey.SelectAll" in source


def test_batch_delete_uses_delete_books_for_selected_ids() -> None:
    source = Path("app/gui/main_window.py").read_text(encoding="utf-8")

    assert "def _selected_batch_book_ids" in source
    assert "delete_books([int(book[\"id\"]) for book in books])" in source
    assert "AI 建议、搜索缓存、AI 请求日志" in source
