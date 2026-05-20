from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import cast

from PySide6.QtCore import Qt
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from app.core.config import load_config, save_config
from app.core.models import ComicMetadata, ImportResult, LightBookError, MangaDirection
from app.exporters.cbz_exporter import export_cbz
from app.importers.comic_epub_importer import import_comic_epub
from app.importers.image_folder_importer import import_image_folder
from app.services.batch_import_service import batch_import
from app.storage.repositories import (
    RowDict,
    create_work,
    delete_book,
    delete_work,
    get_book,
    get_work,
    list_books_by_work,
    list_books,
    list_books_by_status,
    list_works,
    update_book,
    update_work,
)
from app.utils.filename_parser import parse_comic_filename
from app.utils.natural_sort import natural_sorted

logger = logging.getLogger(__name__)

ImporterFunc = Callable[[str | Path], ImportResult]
BATCH_TABLE_COLUMNS = ["状态", "作品名", "卷号", "页数", "来源路径"]


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("LightBook Studio")
        self.resize(1180, 760)

        self.config = load_config()
        self.import_result: ImportResult | None = None
        self.output_root = Path(self.config.recent_output_dir) if self.config.recent_output_dir else None
        self.current_batch_book_id: int | None = None

        self._create_single_import_widgets()
        self._create_batch_widgets()
        self._create_settings_widgets()
        self._build_ui()
        self._refresh_output_labels()
        self._refresh_batch_table()

    def _create_single_import_widgets(self) -> None:
        self.source_label = QLabel("未选择")
        self.page_count_label = QLabel("0")
        self.output_label = QLabel("未选择")
        self.cover_label = QLabel()
        self.cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover_label.setMinimumSize(220, 300)
        self.cover_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.cover_label.setStyleSheet("border: 1px solid #cccccc; background: #fafafa;")

        self.warning_box = QTextEdit()
        self.warning_box.setReadOnly(True)
        self.warning_box.setMaximumHeight(110)

        self.file_list = QListWidget()
        self.file_list.setMaximumHeight(180)

        self.series_title_edit = QLineEdit()
        self.book_title_edit = QLineEdit()
        self.volume_number_edit = QLineEdit("1")
        self.author_edit = QLineEdit()
        self.translator_edit = QLineEdit()
        self.summary_edit = QTextEdit()
        self.summary_edit.setMaximumHeight(120)
        self.genres_edit = QLineEdit()
        self.tags_edit = QLineEdit()
        self.language_edit = QLineEdit("zh")
        self.direction_combo = QComboBox()
        self.direction_combo.addItems(["rtl", "ltr", "webtoon"])

    def _create_batch_widgets(self) -> None:
        self.batch_table = QTableWidget(0, len(BATCH_TABLE_COLUMNS))
        self.batch_table.setHorizontalHeaderLabels(BATCH_TABLE_COLUMNS)
        self.batch_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.batch_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.batch_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.batch_table.verticalHeader().setVisible(False)
        self.batch_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.batch_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.batch_table.itemSelectionChanged.connect(self._on_batch_selection_changed)
        self.batch_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.batch_table.customContextMenuRequested.connect(self._show_batch_context_menu)

        self.batch_series_title_edit = QLineEdit()
        self.batch_book_title_edit = QLineEdit()
        self.batch_volume_number_edit = QLineEdit()
        self.batch_author_edit = QLineEdit()
        self.batch_translator_edit = QLineEdit()
        self.batch_summary_edit = QTextEdit()
        self.batch_summary_edit.setMaximumHeight(130)
        self.batch_genres_edit = QLineEdit()
        self.batch_tags_edit = QLineEdit()
        self.batch_language_edit = QLineEdit("zh")
        self.batch_direction_combo = QComboBox()
        self.batch_direction_combo.addItems(["rtl", "ltr", "webtoon"])

    def _create_settings_widgets(self) -> None:
        self.settings_output_label = QLabel("未选择")

    def _build_ui(self) -> None:
        tabs = QTabWidget()
        tabs.addTab(self._build_single_import_tab(), "单本导入")
        tabs.addTab(self._build_batch_tab(), "批量整理")
        tabs.addTab(self._build_settings_tab(), "设置")
        self.setCentralWidget(tabs)

    def _build_single_import_tab(self) -> QWidget:
        choose_folder_button = QPushButton("选择图片文件夹")
        choose_folder_button.clicked.connect(self._choose_image_folder)
        choose_epub_button = QPushButton("选择 EPUB")
        choose_epub_button.clicked.connect(self._choose_epub)
        choose_output_button = QPushButton("选择输出目录")
        choose_output_button.clicked.connect(self._choose_output)
        export_button = QPushButton("导出 CBZ")
        export_button.clicked.connect(self._export)

        top_buttons = QHBoxLayout()
        top_buttons.addWidget(choose_folder_button)
        top_buttons.addWidget(choose_epub_button)
        top_buttons.addWidget(choose_output_button)
        top_buttons.addStretch()
        top_buttons.addWidget(export_button)

        info_form = QFormLayout()
        info_form.addRow("来源路径", self.source_label)
        info_form.addRow("输出目录", self.output_label)
        info_form.addRow("页数", self.page_count_label)
        info_form.addRow("Warnings", self.warning_box)
        info_form.addRow("文件列表前 20 项", self.file_list)

        metadata_form = QFormLayout()
        metadata_form.addRow("作品名", self.series_title_edit)
        metadata_form.addRow("本卷标题", self.book_title_edit)
        metadata_form.addRow("卷号", self.volume_number_edit)
        metadata_form.addRow("作者", self.author_edit)
        metadata_form.addRow("译者/汉化组", self.translator_edit)
        metadata_form.addRow("简介", self.summary_edit)
        metadata_form.addRow("分类，逗号分隔", self.genres_edit)
        metadata_form.addRow("标签，逗号分隔", self.tags_edit)
        metadata_form.addRow("语言", self.language_edit)
        metadata_form.addRow("阅读方向", self.direction_combo)

        left = QVBoxLayout()
        left.addLayout(info_form)
        left.addLayout(metadata_form)

        content = QHBoxLayout()
        content.addLayout(left, stretch=2)
        content.addWidget(self.cover_label, stretch=1)

        root = QVBoxLayout()
        root.addLayout(top_buttons)
        root.addLayout(content)

        container = QWidget()
        container.setLayout(root)
        return container

    def _build_batch_tab(self) -> QWidget:
        choose_epubs_button = QPushButton("选择多个 EPUB")
        choose_epubs_button.clicked.connect(self._batch_choose_epubs)
        choose_folders_button = QPushButton("选择多个图片文件夹")
        choose_folders_button.clicked.connect(self._batch_choose_image_folders)
        scan_epubs_button = QPushButton("扫描目录中的 EPUB")
        scan_epubs_button.clicked.connect(self._batch_scan_epubs)
        refresh_button = QPushButton("刷新")
        refresh_button.clicked.connect(self._refresh_batch_table)
        delete_selected_button = QPushButton("删除选中")
        delete_selected_button.clicked.connect(self._delete_selected_batch_book)

        top_buttons = QHBoxLayout()
        top_buttons.addWidget(choose_epubs_button)
        top_buttons.addWidget(choose_folders_button)
        top_buttons.addWidget(scan_epubs_button)
        top_buttons.addStretch()
        top_buttons.addWidget(delete_selected_button)
        top_buttons.addWidget(refresh_button)

        form = QFormLayout()
        form.addRow("series_title", self.batch_series_title_edit)
        form.addRow("book_title", self.batch_book_title_edit)
        form.addRow("volume_number", self.batch_volume_number_edit)
        form.addRow("author", self.batch_author_edit)
        form.addRow("translator", self.batch_translator_edit)
        form.addRow("summary", self.batch_summary_edit)
        form.addRow("genres", self.batch_genres_edit)
        form.addRow("tags", self.batch_tags_edit)
        form.addRow("language_iso", self.batch_language_edit)
        form.addRow("manga_direction", self.batch_direction_combo)

        save_button = QPushButton("保存修改")
        save_button.clicked.connect(lambda: self._save_batch_metadata())
        export_selected_button = QPushButton("导出选中项")
        export_selected_button.clicked.connect(self._export_selected_batch_book)
        export_ready_button = QPushButton("导出全部 ready")
        export_ready_button.clicked.connect(self._export_all_ready_books)

        action_buttons = QHBoxLayout()
        action_buttons.addWidget(save_button)
        action_buttons.addWidget(export_selected_button)
        action_buttons.addWidget(export_ready_button)

        form_container = QWidget()
        form_layout = QVBoxLayout()
        form_layout.addLayout(form)
        form_layout.addLayout(action_buttons)
        form_layout.addStretch()
        form_container.setLayout(form_layout)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.batch_table)
        splitter.addWidget(form_container)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        root = QVBoxLayout()
        root.addLayout(top_buttons)
        root.addWidget(splitter)

        container = QWidget()
        container.setLayout(root)
        return container

    def _build_settings_tab(self) -> QWidget:
        choose_output_button = QPushButton("选择输出目录")
        choose_output_button.clicked.connect(self._choose_output)

        form = QFormLayout()
        form.addRow("输出目录", self.settings_output_label)
        form.addRow("", choose_output_button)

        root = QVBoxLayout()
        root.addLayout(form)
        root.addStretch()

        container = QWidget()
        container.setLayout(root)
        return container

    def _choose_image_folder(self) -> None:
        start_dir = self.config.recent_input_dir or str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, "选择图片文件夹", start_dir)
        if not folder:
            return
        self._load_source(Path(folder), import_image_folder)

    def _choose_epub(self) -> None:
        start_dir = self.config.recent_input_dir or str(Path.home())
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择 EPUB",
            start_dir,
            "EPUB Files (*.epub);;All Files (*)",
        )
        if not file_path:
            return
        self._load_source(Path(file_path), import_comic_epub)

    def _choose_output(self) -> None:
        start_dir = self.config.recent_output_dir or str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, "选择输出目录", start_dir)
        if not folder:
            return
        self.output_root = Path(folder)
        self.config.recent_output_dir = str(self.output_root)
        save_config(self.config)
        self._refresh_output_labels()

    def _refresh_output_labels(self) -> None:
        text = str(self.output_root) if self.output_root else "未选择"
        self.output_label.setText(text)
        self.settings_output_label.setText(text)

    def _load_source(self, path: Path, importer: ImporterFunc) -> None:
        try:
            result = importer(path)
        except LightBookError as exc:
            self._show_error(str(exc))
            return
        except Exception as exc:
            logger.exception("Unexpected import error")
            self._show_error(f"导入失败：{exc}")
            return

        self.import_result = result
        recent_dir = path if path.is_dir() else path.parent
        self.config.recent_input_dir = str(recent_dir)
        save_config(self.config)
        self._populate_import_result(result)

    def _populate_import_result(self, result: ImportResult) -> None:
        self.source_label.setText(str(result.source_path))
        self.page_count_label.setText(str(len(result.pages)))
        self.warning_box.setPlainText("\n".join(result.warnings))
        self.file_list.clear()
        for page in result.pages[:20]:
            self.file_list.addItem(page.display_name)

        self._populate_metadata(result.metadata)
        pixmap = QPixmap()
        pixmap.loadFromData(result.cover_data)
        if not pixmap.isNull():
            self.cover_label.setPixmap(
                pixmap.scaled(
                    self.cover_label.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        else:
            self.cover_label.setText("无法预览封面")

    def _populate_metadata(self, metadata: ComicMetadata) -> None:
        self.series_title_edit.setText(metadata.series_title)
        self.book_title_edit.setText(metadata.book_title)
        self.volume_number_edit.setText(str(metadata.volume_number))
        self.author_edit.setText(metadata.author)
        self.translator_edit.setText(metadata.translator)
        self.summary_edit.setPlainText(metadata.summary)
        self.genres_edit.setText(", ".join(metadata.genres))
        self.tags_edit.setText(", ".join(metadata.tags))
        self.language_edit.setText(metadata.language_iso or "zh")
        index = self.direction_combo.findText(metadata.manga_direction)
        self.direction_combo.setCurrentIndex(index if index >= 0 else 0)

    def _metadata_from_form(self) -> ComicMetadata:
        try:
            volume_number = int(self.volume_number_edit.text().strip() or "1")
        except ValueError as exc:
            raise LightBookError("卷号必须是整数。") from exc

        return ComicMetadata(
            series_title=self.series_title_edit.text().strip(),
            book_title=self.book_title_edit.text().strip(),
            volume_number=volume_number,
            author=self.author_edit.text().strip(),
            translator=self.translator_edit.text().strip(),
            summary=self.summary_edit.toPlainText().strip(),
            genres=_split_terms(self.genres_edit.text()),
            tags=_split_terms(self.tags_edit.text()),
            language_iso=self.language_edit.text().strip() or "zh",
            manga_direction=cast(MangaDirection, self.direction_combo.currentText()),
        )

    def _export(self) -> None:
        if self.import_result is None:
            self._show_error("请先选择图片文件夹或 EPUB。")
            return
        if self.output_root is None:
            self._show_error("请先选择输出目录。")
            return

        try:
            metadata = self._metadata_from_form()
            result = export_cbz(self.import_result, self.output_root, metadata)
        except LightBookError as exc:
            self._show_error(str(exc))
            return
        except Exception as exc:
            logger.exception("Unexpected export error")
            self._show_error(f"导出失败：{exc}")
            return

        self.config.recent_output_dir = str(self.output_root)
        save_config(self.config)
        QMessageBox.information(
            self,
            "导出完成",
            f"CBZ：{result.cbz_path}\nPoster：{result.poster_path}",
        )

    def _batch_choose_epubs(self) -> None:
        start_dir = self.config.recent_input_dir or str(Path.home())
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "选择多个 EPUB",
            start_dir,
            "EPUB Files (*.epub);;All Files (*)",
        )
        if files:
            self._run_batch_import([Path(file_path) for file_path in files])

    def _batch_choose_image_folders(self) -> None:
        folders = self._choose_multiple_directories()
        if folders:
            self._run_batch_import(folders)

    def _batch_scan_epubs(self) -> None:
        start_dir = self.config.recent_input_dir or str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, "扫描目录中的 EPUB", start_dir)
        if not folder:
            return
        root = Path(folder)
        paths = natural_sorted(
            [path for path in root.rglob("*") if path.is_file() and path.suffix.casefold() == ".epub"],
            key=lambda path: str(path),
        )
        if not paths:
            QMessageBox.information(self, "批量整理", "没有找到 EPUB 文件。")
            return
        self._run_batch_import(paths)

    def _choose_multiple_directories(self) -> list[Path]:
        start_dir = self.config.recent_input_dir or str(Path.home())
        dialog = QFileDialog(self, "选择多个图片文件夹", start_dir)
        dialog.setFileMode(QFileDialog.FileMode.Directory)
        dialog.setOption(QFileDialog.Option.ShowDirsOnly, True)
        dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        for view_type in (QListView, QTreeView):
            for view in dialog.findChildren(view_type):
                view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        if not dialog.exec():
            return []
        return [Path(path) for path in dialog.selectedFiles()]

    def _run_batch_import(self, paths: list[Path]) -> None:
        try:
            result = batch_import(paths)
        except Exception as exc:
            logger.exception("Unexpected batch import error")
            self._show_error(f"批量导入失败：{exc}")
            return

        if paths:
            first = paths[0]
            self.config.recent_input_dir = str(first if first.is_dir() else first.parent)
            save_config(self.config)

        selected_book_id = result.book_ids[-1] if result.book_ids else None
        self._refresh_batch_table(selected_book_id=selected_book_id)

        message = f"导入成功：{result.imported_count}\n导入失败：{result.failed_count}"
        if result.errors:
            message += "\n\n" + "\n".join(result.errors[:10])
            QMessageBox.warning(self, "批量整理", message)
        else:
            QMessageBox.information(self, "批量整理", message)

    def _refresh_batch_table(self, selected_book_id: int | None = None) -> None:
        current_book_id = selected_book_id or self.current_batch_book_id
        try:
            books = list_books()
        except Exception as exc:
            logger.exception("Failed to list books")
            self._show_error(f"读取数据库失败：{exc}")
            return

        self.batch_table.blockSignals(True)
        self.batch_table.setRowCount(0)
        selected_row = -1
        for row_index, book in enumerate(books):
            work = get_work(int(book["work_id"])) or {}
            self.batch_table.insertRow(row_index)
            row_values = [
                str(book.get("status") or ""),
                str(work.get("title") or ""),
                "" if book.get("volume_number") is None else str(book.get("volume_number")),
                str(book.get("page_count") or 0),
                str(book.get("source_path") or ""),
            ]
            for column_index, value in enumerate(row_values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, int(book["id"]))
                self.batch_table.setItem(row_index, column_index, item)
            if current_book_id is not None and int(book["id"]) == current_book_id:
                selected_row = row_index
        self.batch_table.blockSignals(False)

        if selected_row >= 0:
            self.batch_table.selectRow(selected_row)
            self._load_batch_book(current_book_id)
        elif self.batch_table.rowCount() > 0:
            self.batch_table.selectRow(0)
            self._on_batch_selection_changed()
        else:
            self.current_batch_book_id = None
            self._clear_batch_form()

    def _on_batch_selection_changed(self) -> None:
        book_id = self._selected_batch_book_id()
        if book_id is not None:
            self._load_batch_book(book_id)

    def _selected_batch_book_id(self) -> int | None:
        row = self.batch_table.currentRow()
        if row < 0:
            return None
        item = self.batch_table.item(row, 0)
        if item is None:
            return None
        book_id = item.data(Qt.ItemDataRole.UserRole)
        return int(book_id) if book_id is not None else None

    def _show_batch_context_menu(self, position: object) -> None:
        row = self.batch_table.indexAt(position).row()  # type: ignore[arg-type]
        if row < 0:
            return
        self.batch_table.selectRow(row)

        menu = QMenu(self)
        delete_action = menu.addAction("删除")
        open_folder_action = menu.addAction("打开来源文件夹")
        reparse_action = menu.addAction("重新解析")
        selected_action = menu.exec(self.batch_table.viewport().mapToGlobal(position))  # type: ignore[arg-type]

        if selected_action == delete_action:
            self._delete_selected_batch_book()
        elif selected_action == open_folder_action:
            self._open_selected_source_folder()
        elif selected_action == reparse_action:
            self._reparse_selected_batch_book()

    def _delete_selected_batch_book(self) -> None:
        book_id = self._selected_batch_book_id()
        if book_id is None:
            self._show_error("请先选择一个 book。")
            return

        book = get_book(book_id)
        if book is None:
            self._show_error("找不到选中的 book。")
            self._refresh_batch_table()
            return

        source_path = str(book.get("source_path") or "")
        answer = QMessageBox.question(
            self,
            "删除",
            "从批量整理列表和数据库中删除选中项？\n"
            f"{source_path}\n\n"
            "磁盘上的 EPUB 或图片文件夹不会被删除。",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        work_id = int(book["work_id"])
        try:
            delete_book(book_id)
            self.current_batch_book_id = None
            if not list_books_by_work(work_id):
                delete_empty_answer = QMessageBox.question(
                    self,
                    "删除空作品",
                    "这个 work 下已经没有 book，是否同时删除空 work？",
                )
                if delete_empty_answer == QMessageBox.StandardButton.Yes:
                    delete_work(work_id)
        except Exception as exc:
            logger.exception("Failed to delete batch book")
            self._show_error(f"删除失败：{exc}")
            return

        self._refresh_batch_table()

    def _open_selected_source_folder(self) -> None:
        book_id = self._selected_batch_book_id()
        if book_id is None:
            self._show_error("请先选择一个 book。")
            return
        book = get_book(book_id)
        if book is None:
            self._show_error("找不到选中的 book。")
            return

        source_path = Path(str(book.get("source_path") or ""))
        folder = source_path if source_path.is_dir() else source_path.parent
        if not folder.exists():
            self._show_error(f"来源文件夹不存在：{folder}")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _reparse_selected_batch_book(self) -> None:
        book_id = self._selected_batch_book_id()
        if book_id is None:
            self._show_error("请先选择一个 book。")
            return

        book = get_book(book_id)
        if book is None:
            self._show_error("找不到选中的 book。")
            self._refresh_batch_table()
            return

        try:
            source_path = Path(str(book["source_path"]))
            import_result = self._import_result_for_book(book)
            series_title, book_title, volume_number = _resolve_titles_from_import(
                source_path,
                import_result,
            )
            work = self._work_for_reparsed_book(int(book["work_id"]), series_title, import_result)
            update_book(
                book_id,
                work_id=int(work["id"]),
                title=book_title,
                volume_number=volume_number,
                source_type=import_result.source_type,
                page_count=len(import_result.pages),
                translator=import_result.metadata.translator,
                manga_direction=import_result.metadata.manga_direction,
                status="need_review",
            )
        except Exception as exc:
            logger.exception("Failed to reparse batch book")
            try:
                update_book(book_id, status="failed")
            except Exception:
                logger.exception("Failed to mark reparsed book as failed")
            self._refresh_batch_table(selected_book_id=book_id)
            self._show_error(f"重新解析失败：{exc}")
            return

        self._refresh_batch_table(selected_book_id=book_id)
        QMessageBox.information(self, "批量整理", "已重新解析，状态已更新为 need_review。")

    def _work_for_reparsed_book(
        self,
        current_work_id: int,
        series_title: str,
        import_result: ImportResult,
    ) -> RowDict:
        existing = _find_work_by_title(series_title)
        if existing is not None:
            work_id = int(existing["id"])
        elif len(list_books_by_work(current_work_id)) <= 1:
            work_id = current_work_id
        else:
            work = create_work(title=series_title)
            work_id = int(work["id"])

        metadata = import_result.metadata
        updated = update_work(
            work_id,
            title=series_title,
            author=metadata.author,
            summary=metadata.summary,
            genres=", ".join(metadata.genres),
            tags=", ".join(metadata.tags),
            language_iso=metadata.language_iso or "zh",
        )
        return updated or get_work(work_id) or {"id": work_id, "title": series_title}

    def _load_batch_book(self, book_id: int | None) -> None:
        if book_id is None:
            return
        book = get_book(book_id)
        if book is None:
            self._show_error("找不到选中的 book。")
            return
        work = get_work(int(book["work_id"]))
        if work is None:
            self._show_error("找不到 book 对应的 work。")
            return

        self.current_batch_book_id = book_id
        self.batch_series_title_edit.setText(str(work.get("title") or ""))
        self.batch_book_title_edit.setText(str(book.get("title") or ""))
        self.batch_volume_number_edit.setText(
            "" if book.get("volume_number") is None else str(book.get("volume_number"))
        )
        self.batch_author_edit.setText(str(work.get("author") or ""))
        self.batch_translator_edit.setText(str(book.get("translator") or ""))
        self.batch_summary_edit.setPlainText(str(work.get("summary") or ""))
        self.batch_genres_edit.setText(str(work.get("genres") or ""))
        self.batch_tags_edit.setText(str(work.get("tags") or ""))
        self.batch_language_edit.setText(str(work.get("language_iso") or "zh"))
        direction = str(book.get("manga_direction") or "rtl")
        index = self.batch_direction_combo.findText(direction)
        self.batch_direction_combo.setCurrentIndex(index if index >= 0 else 0)

    def _clear_batch_form(self) -> None:
        self.batch_series_title_edit.clear()
        self.batch_book_title_edit.clear()
        self.batch_volume_number_edit.clear()
        self.batch_author_edit.clear()
        self.batch_translator_edit.clear()
        self.batch_summary_edit.clear()
        self.batch_genres_edit.clear()
        self.batch_tags_edit.clear()
        self.batch_language_edit.setText("zh")
        self.batch_direction_combo.setCurrentIndex(0)

    def _save_batch_metadata(self, show_message: bool = True) -> bool:
        if self.current_batch_book_id is None:
            self._show_error("请先选择一个 book。")
            return False

        book = get_book(self.current_batch_book_id)
        if book is None:
            self._show_error("找不到选中的 book。")
            return False

        try:
            volume_number = _parse_optional_int(
                self.batch_volume_number_edit.text(),
                "volume_number",
            )
            series_title = self.batch_series_title_edit.text().strip() or "Untitled"
            book_title = self.batch_book_title_edit.text().strip() or series_title
            update_work(
                int(book["work_id"]),
                title=series_title,
                author=self.batch_author_edit.text().strip(),
                summary=self.batch_summary_edit.toPlainText().strip(),
                genres=self.batch_genres_edit.text().strip(),
                tags=self.batch_tags_edit.text().strip(),
                language_iso=self.batch_language_edit.text().strip() or "zh",
            )
            update_book(
                self.current_batch_book_id,
                title=book_title,
                volume_number=volume_number,
                translator=self.batch_translator_edit.text().strip(),
                manga_direction=self.batch_direction_combo.currentText(),
                status="ready",
            )
        except LightBookError as exc:
            self._show_error(str(exc))
            return False
        except Exception as exc:
            logger.exception("Failed to save batch metadata")
            self._show_error(f"保存失败：{exc}")
            return False

        self._refresh_batch_table(selected_book_id=self.current_batch_book_id)
        if show_message:
            QMessageBox.information(self, "批量整理", "已保存，状态已更新为 ready。")
        return True

    def _export_selected_batch_book(self) -> None:
        book_id = self._selected_batch_book_id()
        if book_id is None:
            self._show_error("请先选择一个 book。")
            return
        self.current_batch_book_id = book_id
        if not self._save_batch_metadata(show_message=False):
            return
        self._export_batch_books([book_id])

    def _export_all_ready_books(self) -> None:
        ready_books = list_books_by_status("ready")
        if not ready_books:
            QMessageBox.information(self, "批量整理", "没有 ready 状态的 book。")
            return
        self._export_batch_books([int(book["id"]) for book in ready_books])

    def _export_batch_books(self, book_ids: list[int]) -> None:
        if self.output_root is None:
            self._show_error("请先在设置中选择输出目录。")
            return

        errors: list[str] = []
        exported_count = 0
        for book_id in book_ids:
            error = self._export_batch_book(book_id)
            if error is None:
                exported_count += 1
            else:
                errors.append(error)

        self._refresh_batch_table(selected_book_id=book_ids[-1] if book_ids else None)
        message = f"导出成功：{exported_count}\n导出失败：{len(errors)}"
        if errors:
            message += "\n\n" + "\n".join(errors[:10])
            QMessageBox.warning(self, "批量整理", message)
        else:
            QMessageBox.information(self, "批量整理", message)

    def _export_batch_book(self, book_id: int) -> str | None:
        book = get_book(book_id)
        if book is None:
            return f"book {book_id}: 不存在"
        work = get_work(int(book["work_id"]))
        if work is None:
            update_book(book_id, status="failed")
            return f"book {book_id}: 找不到对应 work"

        try:
            import_result = self._import_result_for_book(book)
            metadata = self._metadata_for_batch_export(book, work)
            result = export_cbz(import_result, self.output_root or Path("."), metadata)
            update_book(book_id, status="exported")
            logger.info("Batch exported book %s to %s", book_id, result.cbz_path)
            return None
        except Exception as exc:
            logger.exception("Batch export failed for book %s", book_id)
            update_book(book_id, status="failed")
            return f"{book.get('source_path')}: {exc}"

    def _import_result_for_book(self, book: RowDict) -> ImportResult:
        source_path = Path(str(book["source_path"]))
        source_type = str(book["source_type"])
        if source_type == "epub":
            return import_comic_epub(source_path)
        if source_type == "image_folder":
            return import_image_folder(source_path)
        raise LightBookError(f"不支持的 source_type：{source_type}")

    def _metadata_for_batch_export(self, book: RowDict, work: RowDict) -> ComicMetadata:
        direction = str(book.get("manga_direction") or "rtl")
        if direction not in {"rtl", "ltr", "webtoon"}:
            direction = "rtl"

        return ComicMetadata(
            series_title=str(work.get("title") or "Untitled"),
            book_title=str(book.get("title") or work.get("title") or "Untitled"),
            volume_number=int(book.get("volume_number") or 1),
            author=str(work.get("author") or ""),
            translator=str(book.get("translator") or ""),
            summary=str(work.get("summary") or ""),
            genres=_split_terms(str(work.get("genres") or "")),
            tags=_split_terms(str(work.get("tags") or "")),
            language_iso=str(work.get("language_iso") or "zh"),
            manga_direction=cast(MangaDirection, direction),
        )

    def _show_error(self, message: str) -> None:
        QMessageBox.critical(self, "LightBook Studio", message)


def _split_terms(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _resolve_titles_from_import(
    source_path: Path,
    import_result: ImportResult,
) -> tuple[str, str, int | None]:
    parsed = parse_comic_filename(source_path.name)
    metadata = import_result.metadata
    series_title = (
        parsed.series_title.strip()
        or metadata.series_title.strip()
        or metadata.book_title.strip()
        or source_path.stem
        or "Untitled"
    )
    book_title = (
        parsed.book_title.strip()
        or metadata.book_title.strip()
        or metadata.series_title.strip()
        or series_title
    )
    return series_title, book_title, parsed.volume_number


def _find_work_by_title(title: str) -> RowDict | None:
    for work in list_works():
        if str(work.get("title") or "") == title:
            return work
    return None


def _parse_optional_int(value: str, field_name: str) -> int | None:
    text = value.strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError as exc:
        raise LightBookError(f"{field_name} 必须是整数。") from exc
