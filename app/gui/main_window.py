from __future__ import annotations

import json
import logging
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from PySide6.QtCore import Qt
from PySide6.QtCore import QUrl
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
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
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QDoubleSpinBox,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from app.core.config import load_config, save_config
from app.core.logging_config import LOG_DIR, LOG_FILE
from app.core.models import ComicMetadata, ImportResult, LightBookError, MangaDirection
from app.ai.config import AiProviderConfig, load_ai_provider_config, save_ai_provider_config
from app.ai.openai_compatible_provider import AiProviderConfigError, OpenAICompatibleProvider
from app.ai.provider_factory import create_ai_provider
from app.ai.suggestion_service import AiSuggestionService
from app.exporters.cbz_exporter import export_cbz
from app.exporters.epub_exporter import export_novel_epub
from app.importers.cbz_importer import import_cbz
from app.importers.comic_epub_importer import import_comic_epub
from app.importers.image_folder_importer import import_image_folder
from app.importers.novel_txt_importer import NovelImportResult, import_novel_txt
from app.parsers.novel_chapter_parser import NovelChapter
from app.services.batch_export_service import export_book_from_database, export_novel_preview_from_database
from app.search.mock_search_provider import MockSearchProvider
from app.search.web_search_service import MetadataSearchService
from app.services.batch_import_service import batch_import
from app.services.output_planner import plan_novel_output
from app.storage.repositories import (
    RowDict,
    bulk_update_book_status,
    create_work,
    create_novel_chapter,
    delete_novel_chapters_by_book,
    delete_books,
    get_book,
    get_work,
    list_novel_chapters,
    create_ai_suggestion,
    get_ai_suggestion,
    list_latest_ai_suggestion_by_book,
    get_setting,
    list_books_by_work,
    list_books,
    list_books_by_status,
    update_novel_chapter_title,
    list_works,
    set_setting,
    update_book,
    update_work,
)
from app.utils.filename_parser import parse_comic_filename
from app.utils.filename import sanitize_windows_filename
from app.utils.image_utils import is_supported_image_path
from app.utils.natural_sort import natural_sorted

logger = logging.getLogger(__name__)

ImporterFunc = Callable[[str | Path], ImportResult]
AI_APPLY_FIELDS = [
    ("clean_title", "作品名", True),
    ("original_title", "原名", True),
    ("aliases", "别名", False),
    ("book_title", "本卷标题", True),
    ("volume_number", "卷号", True),
    ("authors", "作者", True),
    ("illustrators", "插画", False),
    ("translators", "译者", True),
    ("summary", "简介", True),
    ("genres", "分类", True),
    ("tags", "标签", True),
    ("language_iso", "语言", True),
    ("manga_direction", "阅读方向", True),
    ("series_status", "连载状态", False),
]
BATCH_TABLE_COLUMNS = ["类型", "状态", "作品名", "卷号", "页数 / 章节数", "来源路径"]


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("LightBook Studio")
        self.resize(1600, 950)

        self.config = load_config()
        self.import_result: ImportResult | None = None
        self.novel_import_result: NovelImportResult | None = None
        self.single_cover_override_path: Path | None = None
        self.batch_cover_override_path: Path | None = None
        self.output_root = Path(self.config.recent_output_dir) if self.config.recent_output_dir else None
        self.current_batch_book_id: int | None = None
        self.current_ai_suggestion_id: int | None = None
        self.current_ai_suggestion_row: RowDict | None = None

        self._install_exception_hook()

        self._create_single_import_widgets()
        self._create_batch_widgets()
        self._create_settings_widgets()
        self._build_ui()
        self._apply_flat_style()
        self._refresh_output_labels()
        self._refresh_batch_table()

        logger.info("GUI 窗口已创建")

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
        self.single_cover_override_label = QLabel("未选择")
        self.single_choose_cover_button = QPushButton("选择封面")
        self.single_choose_cover_button.clicked.connect(self._choose_single_cover)
        self.single_clear_cover_button = QPushButton("清除封面")
        self.single_clear_cover_button.clicked.connect(self._clear_single_cover)

    def _create_batch_widgets(self) -> None:
        self.batch_table = QTableWidget(0, len(BATCH_TABLE_COLUMNS))
        self.batch_table.setHorizontalHeaderLabels(BATCH_TABLE_COLUMNS)
        self.batch_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.batch_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.batch_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.batch_table.verticalHeader().setVisible(False)
        self.batch_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.batch_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.batch_table.itemSelectionChanged.connect(self._on_batch_selection_changed)
        self.batch_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.batch_table.customContextMenuRequested.connect(self._show_batch_context_menu)
        self.batch_select_all_shortcut = QShortcut(QKeySequence.StandardKey.SelectAll, self.batch_table)
        self.batch_select_all_shortcut.activated.connect(self.batch_table.selectAll)

        self.batch_series_title_edit = QLineEdit()
        self.batch_book_title_edit = QLineEdit()
        self.batch_volume_number_edit = QLineEdit()
        self.batch_author_edit = QLineEdit()
        self.batch_translator_edit = QLineEdit()
        self.batch_summary_edit = QTextEdit()
        self.batch_summary_edit.setMinimumHeight(180)
        self.batch_summary_edit.setMaximumHeight(320)
        self.batch_genres_edit = QLineEdit()
        self.batch_tags_edit = QLineEdit()
        self.batch_language_edit = QLineEdit("zh")
        self.batch_direction_combo = QComboBox()
        self.batch_direction_combo.addItems(["rtl", "ltr", "webtoon"])
        self.batch_cover_override_label = QLabel("未选择")
        self.batch_choose_cover_button = QPushButton("选择封面")
        self.batch_choose_cover_button.clicked.connect(self._choose_batch_cover)
        self.batch_clear_cover_button = QPushButton("清除封面")
        self.batch_clear_cover_button.clicked.connect(self._clear_batch_cover)
        self.batch_cover_preview_label = QLabel()
        self.batch_cover_preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.batch_cover_preview_label.setMinimumSize(120, 120)
        self.batch_cover_preview_label.setMaximumHeight(160)
        self.batch_cover_preview_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.batch_cover_preview_label.setStyleSheet("border: 1px solid #cccccc; background: #fafafa;")

        self.batch_chapter_label = QLabel("章节列表")
        self.batch_chapter_table = QTableWidget(0, 3)
        self.batch_chapter_table.setHorizontalHeaderLabels(["序号", "章节标题", "字数"])
        self.batch_chapter_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.batch_chapter_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.batch_chapter_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.batch_chapter_table.verticalHeader().setVisible(False)
        self.batch_chapter_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.batch_chapter_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.batch_chapter_table.itemSelectionChanged.connect(self._on_chapter_selection_changed)

        self.batch_chapter_title_label = QLabel("章节标题")
        self.batch_chapter_title_edit = QLineEdit()
        self.batch_save_chapter_title_button = QPushButton("保存章节标题")
        self.batch_save_chapter_title_button.clicked.connect(self._save_selected_chapter_title)
        self.batch_preview_epub_button = QPushButton("生成预览 EPUB")
        self.batch_preview_epub_button.clicked.connect(self._generate_preview_epub)
        self.batch_open_preview_epub_button = QPushButton("打开预览 EPUB")
        self.batch_open_preview_epub_button.clicked.connect(self._open_preview_epub)
        self.batch_chapter_preview_label = QLabel("正文预览")
        self.batch_chapter_preview_edit = QTextEdit()
        self.batch_chapter_preview_edit.setReadOnly(True)
        self.batch_chapter_preview_edit.setMinimumHeight(180)

        self.ai_generate_button = QPushButton("生成 AI 建议")
        self.ai_generate_button.clicked.connect(self._generate_ai_suggestion)
        self.ai_apply_button = QPushButton("应用选中字段")
        self.ai_apply_button.clicked.connect(self._apply_selected_ai_fields)
        self.ai_ignore_button = QPushButton("忽略建议")
        self.ai_ignore_button.clicked.connect(self._ignore_ai_suggestion)
        self.ai_raw_response_button = QPushButton("查看原始响应")
        self.ai_raw_response_button.clicked.connect(self._show_ai_raw_response)
        self.ai_search_button = QPushButton("搜索封面/资料")
        self.ai_search_button.clicked.connect(self._search_cover_and_metadata)
        self.ai_status_label = QLabel("AI 只提供建议，不会自动覆盖数据。")
        self.ai_suggestion_table = QTableWidget(0, 4)
        self.ai_suggestion_table.setHorizontalHeaderLabels(["字段", "当前值", "AI 建议", "应用"])
        self.ai_suggestion_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.ai_suggestion_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.ai_suggestion_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.ai_suggestion_table.setMinimumHeight(260)
        self.ai_suggestion_table.verticalHeader().setVisible(False)
        self.ai_suggestion_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.ai_suggestion_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._set_novel_chapter_widgets_visible(False)

    def _create_settings_widgets(self) -> None:
        self.ai_provider_label = QLabel("OpenAICompatibleProvider")
        self.ai_provider_combo = QComboBox()
        self.ai_provider_combo.addItem("OpenAI Compatible / DeepSeek", "openai_compatible")
        self.ai_provider_combo.addItem("Mock，仅开发测试", "mock")
        self.ai_base_url_edit = QLineEdit()
        self.ai_base_url_edit.setPlaceholderText("https://api.openai.com/v1")
        self.ai_base_url_edit.setToolTip("OpenAI-compatible / DeepSeek API 地址。")
        self.ai_model_edit = QLineEdit()
        self.ai_model_edit.setPlaceholderText("填写真实 provider 使用的模型名")
        self.ai_model_edit.setToolTip("预留字段，当前不会自动启用真实 provider。")
        self.ai_api_key_edit = QLineEdit()
        self.ai_api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.ai_api_key_edit.setPlaceholderText("从环境变量 LIGHTBOOK_AI_API_KEY 读取，不在此保存")
        self.ai_api_key_edit.setEnabled(False)
        self.ai_api_key_env_edit = QLineEdit()
        self.ai_api_key_env_edit.setPlaceholderText("LIGHTBOOK_AI_API_KEY")
        self.ai_timeout_spin = QSpinBox()
        self.ai_timeout_spin.setRange(1, 600)
        self.ai_temperature_spin = QDoubleSpinBox()
        self.ai_temperature_spin.setRange(0.0, 2.0)
        self.ai_temperature_spin.setSingleStep(0.1)
        self.ai_temperature_spin.setDecimals(2)
        self.ai_settings_hint_label = QLabel("API Key 请通过环境变量配置，例如 LIGHTBOOK_AI_API_KEY。")
        self.ai_save_settings_button = QPushButton("保存 AI 设置")
        self.ai_save_settings_button.clicked.connect(self._save_ai_settings)
        self.ai_test_connection_button = QPushButton("测试连接")
        self.ai_test_connection_button.clicked.connect(self._test_ai_connection)
        self.ai_api_key_status_label = QLabel(_ai_api_key_status_text())
        self.ai_diagnostic_label = QLabel("")
        self._load_ai_settings_into_widgets()
        self.settings_output_label = QLabel("未选择")

    def _build_ui(self) -> None:
        self._build_menu_bar()
        tabs = QTabWidget()
        tabs.addTab(self._build_single_import_tab(), "单本导入")
        tabs.addTab(self._build_batch_tab(), "批量整理")
        tabs.addTab(self._build_settings_tab(), "设置")
        self.setCentralWidget(tabs)

    def _apply_flat_style(self) -> None:
        self.setStyleSheet("""
            QMainWindow {
                background-color: #f5f5f5;
            }
            QGroupBox {
                border: 1px solid #d8d8d8;
                border-radius: 6px;
                margin-top: 12px;
                padding-top: 14px;
                font-size: 13px;
                font-weight: bold;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
                color: #555;
            }
            QPushButton {
                background-color: #ffffff;
                border: 1px solid #c8c8c8;
                border-radius: 4px;
                padding: 5px 14px;
                font-size: 13px;
                min-height: 26px;
            }
            QPushButton:hover {
                background-color: #e8e8e8;
                border-color: #a0a0a0;
            }
            QPushButton:pressed {
                background-color: #d8d8d8;
            }
            QLineEdit {
                border: 1px solid #c8c8c8;
                border-radius: 4px;
                padding: 5px 8px;
                font-size: 13px;
                background-color: #ffffff;
            }
            QLineEdit:focus {
                border-color: #7eb8e0;
            }
            QTextEdit {
                border: 1px solid #c8c8c8;
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 13px;
                background-color: #ffffff;
            }
            QTextEdit:focus {
                border-color: #7eb8e0;
            }
            QComboBox {
                border: 1px solid #c8c8c8;
                border-radius: 4px;
                padding: 5px 8px;
                font-size: 13px;
                background-color: #ffffff;
            }
            QTableWidget {
                font-size: 13px;
                background-color: #ffffff;
                alternate-background-color: #f9f9f9;
                gridline-color: #e8e8e8;
            }
            QTableWidget::item {
                padding: 6px 8px;
            }
            QTableWidget::item:selected {
                background-color: #d8e8f8;
                color: #222;
            }
            QHeaderView::section {
                background-color: #f0f0f0;
                border: 1px solid #d8d8d8;
                padding: 6px 8px;
                font-size: 13px;
            }
            QScrollArea {
                border: none;
            }
            QTabWidget::pane {
                border: 1px solid #d8d8d8;
                background-color: #ffffff;
            }
            QTabBar::tab {
                border: 1px solid #d8d8d8;
                padding: 7px 18px;
                font-size: 13px;
                background-color: #ececec;
            }
            QTabBar::tab:selected {
                background-color: #ffffff;
                border-bottom-color: #ffffff;
            }
            QLabel {
                font-size: 13px;
            }
            QSpinBox, QDoubleSpinBox {
                border: 1px solid #c8c8c8;
                border-radius: 4px;
                padding: 5px 8px;
                font-size: 13px;
                background-color: #ffffff;
            }
        """)

    def _install_exception_hook(self) -> None:
        original_hook = sys.excepthook

        def hook(exc_type: type, exc_value: BaseException, exc_tb: object) -> None:
            logger.critical("未捕获异常", exc_info=(exc_type, exc_value, exc_tb))
            original_hook(exc_type, exc_value, exc_tb)

        sys.excepthook = hook

    def _build_menu_bar(self) -> None:
        menu_bar = self.menuBar()

        help_menu = menu_bar.addMenu("帮助")

        open_log_action = QAction("打开日志文件", self)
        open_log_action.triggered.connect(self._open_log_file)
        help_menu.addAction(open_log_action)

        open_log_dir_action = QAction("打开日志目录", self)
        open_log_dir_action.triggered.connect(self._open_log_dir)
        help_menu.addAction(open_log_dir_action)

    def _open_log_file(self) -> None:
        if LOG_FILE.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(LOG_FILE.resolve())))
        else:
            QMessageBox.information(self, "日志", f"日志文件尚不存在：\n{LOG_FILE.resolve()}")

    def _open_log_dir(self) -> None:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(LOG_DIR.resolve())))

    def _build_single_import_tab(self) -> QWidget:
        choose_folder_button = QPushButton("选择图片文件夹")
        choose_folder_button.clicked.connect(self._choose_image_folder)
        choose_file_button = QPushButton("选择 EPUB/CBZ/TXT")
        choose_file_button.clicked.connect(self._choose_single_file)
        choose_output_button = QPushButton("选择输出目录")
        choose_output_button.clicked.connect(self._choose_output)
        export_button = QPushButton("导出")
        export_button.clicked.connect(self._export)

        top_buttons = QHBoxLayout()
        top_buttons.addWidget(choose_folder_button)
        top_buttons.addWidget(choose_file_button)
        top_buttons.addWidget(choose_output_button)
        top_buttons.addStretch()
        top_buttons.addWidget(export_button)

        info_form = QFormLayout()
        info_form.addRow("来源路径", self.source_label)
        info_form.addRow("输出目录", self.output_label)
        info_form.addRow("页数", self.page_count_label)
        info_form.addRow("警告", self.warning_box)
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
        cover_buttons = QHBoxLayout()
        cover_buttons.addWidget(self.single_choose_cover_button)
        cover_buttons.addWidget(self.single_clear_cover_button)
        metadata_form.addRow("自定义封面", self.single_cover_override_label)
        metadata_form.addRow("", cover_buttons)

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
        import_files_button = QPushButton("导入文件")
        import_files_button.clicked.connect(self._batch_import_files)
        import_folders_button = QPushButton("导入文件夹")
        import_folders_button.clicked.connect(self._batch_import_folders)
        scan_sources_button = QPushButton("扫描目录")
        scan_sources_button.clicked.connect(self._batch_scan_sources)
        refresh_button = QPushButton("刷新")
        refresh_button.clicked.connect(self._refresh_batch_table)

        top_buttons = QHBoxLayout()
        top_buttons.addWidget(import_files_button)
        top_buttons.addWidget(import_folders_button)
        top_buttons.addWidget(scan_sources_button)
        top_buttons.addStretch()
        top_buttons.addWidget(refresh_button)

        form = QFormLayout()
        form.addRow("作品名", self.batch_series_title_edit)
        form.addRow("本卷标题", self.batch_book_title_edit)
        form.addRow("卷号", self.batch_volume_number_edit)
        form.addRow("作者", self.batch_author_edit)
        form.addRow("译者 / 汉化组", self.batch_translator_edit)
        form.addRow("简介", self.batch_summary_edit)
        form.addRow("分类", self.batch_genres_edit)
        form.addRow("标签", self.batch_tags_edit)
        form.addRow("语言", self.batch_language_edit)
        form.addRow("阅读方向", self.batch_direction_combo)
        batch_cover_buttons = QHBoxLayout()
        batch_cover_buttons.addWidget(self.batch_choose_cover_button)
        batch_cover_buttons.addWidget(self.batch_clear_cover_button)
        form.addRow("自定义封面", self.batch_cover_override_label)
        form.addRow("", batch_cover_buttons)
        form.addRow("封面预览", self.batch_cover_preview_label)

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

        preview_buttons = QHBoxLayout()
        preview_buttons.addWidget(self.batch_save_chapter_title_button)
        preview_buttons.addWidget(self.batch_preview_epub_button)
        preview_buttons.addWidget(self.batch_open_preview_epub_button)

        ai_buttons = QHBoxLayout()
        ai_buttons.addWidget(self.ai_generate_button)
        ai_buttons.addWidget(self.ai_apply_button)
        ai_buttons.addWidget(self.ai_ignore_button)
        ai_buttons.addWidget(self.ai_raw_response_button)
        ai_buttons.addWidget(self.ai_search_button)
        ai_group = QGroupBox("AI 辅助")
        ai_layout = QVBoxLayout()
        ai_layout.addLayout(ai_buttons)
        ai_layout.addWidget(self.ai_status_label)
        ai_layout.addWidget(self.ai_suggestion_table)
        ai_group.setLayout(ai_layout)

        form_container = QWidget()
        form_layout = QVBoxLayout()
        form_layout.addLayout(form)
        form_layout.addLayout(action_buttons)
        form_layout.addWidget(ai_group)
        form_layout.addWidget(self.batch_chapter_label)
        form_layout.addWidget(self.batch_chapter_table)
        form_layout.addWidget(self.batch_chapter_title_label)
        form_layout.addWidget(self.batch_chapter_title_edit)
        form_layout.addLayout(preview_buttons)
        form_layout.addWidget(self.batch_chapter_preview_label)
        form_layout.addWidget(self.batch_chapter_preview_edit)
        form_layout.addStretch()
        form_container.setLayout(form_layout)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        detail_scroll = QScrollArea()
        detail_scroll.setWidgetResizable(True)
        detail_scroll.setWidget(form_container)

        splitter.addWidget(self.batch_table)
        splitter.addWidget(detail_scroll)
        splitter.setStretchFactor(0, 11)
        splitter.setStretchFactor(1, 9)

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
        form.addRow("AI provider", self.ai_provider_label)
        form.addRow("AI base_url", self.ai_base_url_edit)
        form.addRow("AI model", self.ai_model_edit)
        form.addRow("Provider 类型", self.ai_provider_combo)
        form.addRow("API Key 环境变量名", self.ai_api_key_env_edit)
        form.addRow("Timeout 秒数", self.ai_timeout_spin)
        form.addRow("Temperature", self.ai_temperature_spin)
        form.addRow("说明", self.ai_settings_hint_label)
        ai_settings_buttons = QHBoxLayout()
        ai_settings_buttons.addWidget(self.ai_save_settings_button)
        ai_settings_buttons.addWidget(self.ai_test_connection_button)
        form.addRow("", ai_settings_buttons)
        form.addRow("AI api_key", self.ai_api_key_edit)
        form.addRow("AI key 状态", self.ai_api_key_status_label)
        form.addRow("AI 诊断", self.ai_diagnostic_label)

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

    def _choose_single_file(self) -> None:
        start_dir = self.config.recent_input_dir or str(Path.home())
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择 EPUB / CBZ / TXT",
            start_dir,
            "Supported Files (*.epub *.cbz *.txt);;EPUB Files (*.epub);;CBZ Files (*.cbz);;TXT Files (*.txt);;All Files (*)",
        )
        if not file_path:
            return
        path = Path(file_path)
        suffix = path.suffix.casefold()
        if suffix == ".epub":
            self._load_source(path, import_comic_epub)
        elif suffix == ".cbz":
            self._load_source(path, import_cbz)
        elif suffix == ".txt":
            self._load_novel_source(path)
        else:
            self._show_error(f"不支持的文件类型：{path.suffix}")

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

    def _load_ai_settings_into_widgets(self) -> None:
        config = load_ai_provider_config(_GuiAiRepository())
        provider_index = self.ai_provider_combo.findData(config.provider_type)
        self.ai_provider_combo.setCurrentIndex(provider_index if provider_index >= 0 else 0)
        self.ai_base_url_edit.setText(config.base_url)
        self.ai_model_edit.setText(config.model)
        self.ai_api_key_env_edit.setText(config.api_key_env)
        self.ai_timeout_spin.setValue(config.timeout_seconds)
        self.ai_temperature_spin.setValue(config.temperature)
        self.ai_api_key_status_label.setText(_ai_api_key_status_text(config.api_key_env))
        self._refresh_ai_provider_status(config)

    def _ai_config_from_settings_form(self) -> AiProviderConfig:
        return AiProviderConfig(
            provider_type=str(self.ai_provider_combo.currentData() or "openai_compatible"),
            base_url=self.ai_base_url_edit.text().strip() or "https://api.deepseek.com",
            model=self.ai_model_edit.text().strip() or "deepseek-v4-flash",
            api_key_env=self.ai_api_key_env_edit.text().strip() or "LIGHTBOOK_AI_API_KEY",
            timeout_seconds=int(self.ai_timeout_spin.value()),
            temperature=float(self.ai_temperature_spin.value()),
        )

    def _save_ai_settings(self) -> None:
        config = self._ai_config_from_settings_form()
        try:
            save_ai_provider_config(_GuiAiRepository(), config)
        except AiProviderConfigError:
            config = load_ai_provider_config(_GuiAiRepository())
            self._show_error(f"未配置 API Key，请设置环境变量 {config.api_key_env}。")
        except Exception as exc:
            logger.exception("Failed to save AI settings")
            self._show_error(f"保存 AI 设置失败：{exc}")
            return
        self.ai_api_key_status_label.setText(_ai_api_key_status_text(config.api_key_env))
        self._refresh_ai_provider_status(config)
        QMessageBox.information(self, "AI 设置", "AI 设置已保存。")

    def _refresh_ai_provider_status(self, config: AiProviderConfig) -> None:
        provider = create_ai_provider(config)
        provider_class = provider.__class__.__name__
        self.ai_provider_label.setText(provider_class)
        api_key = os.environ.get(config.api_key_env, "")
        self.ai_diagnostic_label.setText(
            "provider_type={provider_type}; class={provider_class}; base_url={base_url}; "
            "model={model}; api_key_env={api_key_env}; api_key_loaded={loaded}; api_key={masked}".format(
                provider_type=config.provider_type,
                provider_class=provider_class,
                base_url=config.base_url,
                model=config.model,
                api_key_env=config.api_key_env,
                loaded=bool(api_key),
                masked=_mask_api_key(api_key),
            )
        )

    def _test_ai_connection(self) -> None:
        config = self._ai_config_from_settings_form()
        if config.provider_type == "mock":
            QMessageBox.information(self, "AI 设置", "Mock Provider 可用。")
            return
        try:
            provider = create_ai_provider(config)
            if isinstance(provider, OpenAICompatibleProvider):
                provider.test_connection()
            else:
                raise LightBookError("当前 provider 不支持测试连接。")
        except AiProviderConfigError:
            self._show_error(f"未配置 API Key，请设置环境变量 {config.api_key_env}。")
            return
        except Exception as exc:
            logger.exception("AI connection test failed")
            self._show_error(f"AI 连接测试失败：{exc}")
            return
        QMessageBox.information(self, "AI 设置", "AI 连接测试成功。")

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
        self.novel_import_result = None
        self.single_cover_override_path = None
        self.single_cover_override_label.setText("未选择")
        recent_dir = path if path.is_dir() else path.parent
        self.config.recent_input_dir = str(recent_dir)
        save_config(self.config)
        self._populate_import_result(result)

    def _load_novel_source(self, path: Path) -> None:
        try:
            result = import_novel_txt(path)
        except LightBookError as exc:
            self._show_error(str(exc))
            return
        except Exception as exc:
            logger.exception("Unexpected novel import error")
            self._show_error(f"导入失败：{exc}")
            return

        self.import_result = None
        self.novel_import_result = result
        self.single_cover_override_path = None
        self.single_cover_override_label.setText("未选择")
        self.config.recent_input_dir = str(path.parent)
        save_config(self.config)
        self._populate_novel_import_result(result)

    def _populate_import_result(self, result: ImportResult) -> None:
        self.source_label.setText(str(result.source_path))
        self.page_count_label.setText(str(len(result.pages)))
        self.warning_box.setPlainText("\n".join(result.warnings))
        self.file_list.clear()
        for page in result.pages[:20]:
            self.file_list.addItem(page.display_name)

        self._populate_metadata(result.metadata)
        self._show_single_import_cover()

    def _populate_novel_import_result(self, result: NovelImportResult) -> None:
        self.source_label.setText(str(result.source_path))
        self.page_count_label.setText(str(result.chapter_count))
        self.warning_box.setPlainText("\n".join(result.warnings))
        self.file_list.clear()
        for chapter in _flatten_novel_import_chapters(result)[:20]:
            self.file_list.addItem(chapter.title)

        series_title, book_title, volume_number = _resolve_titles_from_novel_import(
            result.source_path,
            result,
        )
        self.series_title_edit.setText(series_title)
        self.book_title_edit.setText(book_title)
        self.volume_number_edit.setText("" if volume_number is None else str(volume_number))
        self.author_edit.setText(result.author_guess)
        self.translator_edit.clear()
        self.summary_edit.clear()
        self.genres_edit.clear()
        self.tags_edit.clear()
        self.language_edit.setText("zh")
        self.direction_combo.setCurrentIndex(0)
        self.cover_label.clear()
        self.cover_label.setText("未选择封面")

    def _choose_single_cover(self) -> None:
        path = self._choose_cover_path()
        if path is None:
            return
        self.single_cover_override_path = path
        self.single_cover_override_label.setText(str(path))
        self._show_cover_file(self.cover_label, path)

    def _clear_single_cover(self) -> None:
        self.single_cover_override_path = None
        self.single_cover_override_label.setText("未选择")
        self._show_single_import_cover()

    def _show_single_import_cover(self) -> None:
        if self.single_cover_override_path is not None:
            self._show_cover_file(self.cover_label, self.single_cover_override_path)
            return
        if self.import_result is not None:
            self._show_cover_bytes(self.cover_label, self.import_result.cover_data)
        else:
            self.cover_label.clear()
            self.cover_label.setText("未选择封面")

    def _choose_batch_cover(self) -> None:
        path = self._choose_cover_path()
        if path is None:
            return
        self.batch_cover_override_path = path
        self.batch_cover_override_label.setText(str(path))
        self._show_cover_file(self.batch_cover_preview_label, path)

    def _clear_batch_cover(self) -> None:
        self.batch_cover_override_path = None
        self.batch_cover_override_label.setText("未选择")
        self.batch_cover_preview_label.clear()
        self.batch_cover_preview_label.setText("未选择封面")

    def _choose_cover_path(self) -> Path | None:
        start_dir = self.config.recent_input_dir or str(Path.home())
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择封面",
            start_dir,
            "Image Files (*.jpg *.jpeg *.png *.webp *.gif);;All Files (*)",
        )
        if not file_path:
            return None
        path = Path(file_path)
        if not is_supported_image_path(path):
            self._show_error("请选择 jpg、jpeg、png、webp 或 gif 封面文件。")
            return None
        return path

    def _show_cover_file(self, label: QLabel, path: Path) -> None:
        pixmap = QPixmap(str(path))
        self._set_cover_pixmap(label, pixmap, "无法预览封面")

    def _show_cover_bytes(self, label: QLabel, data: bytes) -> None:
        pixmap = QPixmap()
        pixmap.loadFromData(data)
        self._set_cover_pixmap(label, pixmap, "无法预览封面")

    def _set_cover_pixmap(self, label: QLabel, pixmap: QPixmap, fallback_text: str) -> None:
        if pixmap.isNull():
            label.clear()
            label.setText(fallback_text)
            return
        label.setPixmap(
            pixmap.scaled(
                label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

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
        if self.import_result is None and self.novel_import_result is None:
            self._show_error("请先选择图片文件夹、EPUB、CBZ 或 TXT。")
            return
        if self.output_root is None:
            self._show_error("请先选择输出目录。")
            return

        try:
            if self.import_result is not None:
                metadata = self._metadata_from_form()
                result = export_cbz(
                    self.import_result,
                    self.output_root,
                    metadata,
                    cover_override_path=self.single_cover_override_path,
                )
                message = f"CBZ：{result.cbz_path}\nPoster：{result.poster_path}"
            else:
                output_path = self._export_single_novel()
                message = f"EPUB：{output_path}"
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
            message,
        )

    def _export_single_novel(self) -> Path:
        if self.novel_import_result is None or self.output_root is None:
            raise LightBookError("请先选择轻小说 TXT 和输出目录。")
        chapters = _flatten_novel_import_chapters(self.novel_import_result)
        if not chapters:
            raise LightBookError("没有可导出的小说章节。")
        volume_number = _parse_optional_int(self.volume_number_edit.text(), "volume_number")
        series_title = self.series_title_edit.text().strip() or "未命名轻小说"
        book_title = self.book_title_edit.text().strip() or series_title
        planned = plan_novel_output(self.output_root, series_title, book_title, volume_number)
        planned.series_dir.mkdir(parents=True, exist_ok=True)
        return export_novel_epub(
            series_title=series_title,
            book_title=book_title,
            volume_number=volume_number,
            author=self.author_edit.text().strip(),
            summary=self.summary_edit.toPlainText().strip(),
            language_iso=self.language_edit.text().strip() or "zh",
            genres=_split_terms(self.genres_edit.text()),
            tags=_split_terms(self.tags_edit.text()),
            chapters=chapters,
            output_path=planned.epub_path,
            cover_path=self.single_cover_override_path,
        )

    def _batch_import_files(self) -> None:
        start_dir = self.config.recent_input_dir or str(Path.home())
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "导入文件",
            start_dir,
            "Supported Files (*.epub *.cbz *.txt);;EPUB Files (*.epub);;CBZ Files (*.cbz);;TXT Files (*.txt);;All Files (*)",
        )
        if files:
            self._run_batch_import([Path(file_path) for file_path in files])

    def _batch_import_folders(self) -> None:
        folders = self._choose_multiple_directories("导入文件夹")
        if folders:
            self._run_batch_import(folders)

    def _batch_scan_sources(self) -> None:
        start_dir = self.config.recent_input_dir or str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, "扫描目录", start_dir)
        if not folder:
            return
        root = Path(folder)
        supported_suffixes = {".epub", ".cbz", ".txt"}
        paths = natural_sorted(
            [path for path in root.rglob("*") if path.is_file() and path.suffix.casefold() in supported_suffixes],
            key=lambda path: str(path),
        )
        if not paths:
            QMessageBox.information(self, "批量整理", "没有找到 EPUB、CBZ 或 TXT 文件。")
            return
        self._run_batch_import(paths)

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

    def _batch_choose_txt(self) -> None:
        start_dir = self.config.recent_input_dir or str(Path.home())
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择 TXT 文件",
            start_dir,
            "TXT Files (*.txt);;All Files (*)",
        )
        if file_path:
            self._run_batch_import([Path(file_path)])

    def _batch_choose_txts(self) -> None:
        start_dir = self.config.recent_input_dir or str(Path.home())
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "选择多个 TXT 文件",
            start_dir,
            "TXT Files (*.txt);;All Files (*)",
        )
        if files:
            self._run_batch_import([Path(file_path) for file_path in files])

    def _batch_choose_image_folders(self) -> None:
        folders = self._choose_multiple_directories("选择多个图片文件夹")
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

    def _batch_scan_txts(self) -> None:
        start_dir = self.config.recent_input_dir or str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, "扫描目录中的 TXT", start_dir)
        if not folder:
            return
        root = Path(folder)
        paths = natural_sorted(
            [path for path in root.rglob("*") if path.is_file() and path.suffix.casefold() == ".txt"],
            key=lambda path: str(path),
        )
        if not paths:
            QMessageBox.information(self, "批量整理", "没有找到 TXT 文件。")
            return
        self._run_batch_import(paths)

    def _choose_multiple_directories(self, title: str = "选择多个图片文件夹") -> list[Path]:
        start_dir = self.config.recent_input_dir or str(Path.home())
        dialog = QFileDialog(self, title, start_dir)
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
        warnings = self._batch_import_warnings(result.book_ids)
        if result.errors:
            message += "\n\n" + "\n".join(_format_batch_error(error) for error in result.errors[:10])
        if warnings:
            message += "\n\n" + "\n".join(warnings[:10])
        if result.errors or warnings:
            QMessageBox.warning(self, "批量整理", message)
        else:
            QMessageBox.information(self, "批量整理", message)

    def _batch_import_warnings(self, book_ids: list[int]) -> list[str]:
        warnings: list[str] = []
        for book_id in book_ids:
            book = get_book(book_id)
            if book is None or not _is_novel_db_book(book):
                continue
            if int(book.get("chapter_count") or 0) == 0:
                warnings.append(f"没识别到章节：{book.get('source_path')}")
        return warnings

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
            count_value = book.get("chapter_count") if _is_novel_db_book(book) else book.get("page_count")
            self.batch_table.insertRow(row_index)
            row_values = [
                _display_media_type(_book_media_type(book)),
                _display_status(str(book.get("status") or "")),
                str(work.get("title") or ""),
                "" if book.get("volume_number") is None else str(book.get("volume_number")),
                str(count_value or 0),
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

    def _selected_batch_book_ids(self) -> list[int]:
        selected_rows = self.batch_table.selectionModel().selectedRows()
        row_numbers = sorted({index.row() for index in selected_rows})
        book_ids: list[int] = []
        for row in row_numbers:
            item = self.batch_table.item(row, 0)
            if item is None:
                continue
            book_id = item.data(Qt.ItemDataRole.UserRole)
            if book_id is not None:
                book_ids.append(int(book_id))
        if not book_ids:
            book_id = self._selected_batch_book_id()
            if book_id is not None:
                book_ids.append(book_id)
        return book_ids

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
        if not self.batch_table.selectionModel().isRowSelected(row, self.batch_table.rootIndex()):
            self.batch_table.selectRow(row)
        else:
            self.batch_table.setCurrentCell(row, 0)

        menu = QMenu(self)
        mark_ready_action = menu.addAction("标记可导出")
        mark_need_review_action = menu.addAction("标记待确认")
        menu.addSeparator()
        delete_action = menu.addAction("删除")
        open_folder_action = menu.addAction("打开来源文件夹")
        menu.addSeparator()
        reparse_action = menu.addAction("重新解析")
        selected_action = menu.exec(self.batch_table.viewport().mapToGlobal(position))  # type: ignore[arg-type]

        if selected_action == mark_ready_action:
            self._mark_selected_batch_books("ready")
        elif selected_action == mark_need_review_action:
            self._mark_selected_batch_books("need_review")
        elif selected_action == delete_action:
            self._delete_selected_batch_books()
        elif selected_action == open_folder_action:
            self._open_selected_source_folder()
        elif selected_action == reparse_action:
            self._reparse_selected_batch_book()

    def _mark_selected_batch_books(self, status: str) -> None:
        book_ids = self._selected_batch_book_ids()
        if not book_ids:
            self._show_error("请先选择一个或多个 book。")
            return

        try:
            updated_count = bulk_update_book_status(book_ids, status)
        except Exception as exc:
            logger.exception("Failed to update selected batch book statuses")
            self._show_error(f"标记状态失败：{exc}")
            return

        keep_selected = book_ids[-1] if book_ids else None
        self._refresh_batch_table(selected_book_id=keep_selected)
        QMessageBox.information(self, "批量整理", f"已将 {updated_count} 个条目标记为 {status}。")

    def _delete_selected_batch_books(self) -> None:
        book_ids = self._selected_batch_book_ids()
        if not book_ids:
            self._show_error("请先选择一个或多个 book。")
            return

        books = [book for book_id in book_ids if (book := get_book(book_id)) is not None]
        if not books:
            self._show_error("找不到选中的 book。")
            self._refresh_batch_table()
            return

        preview_paths = [str(book.get("source_path") or "") for book in books[:10]]
        extra_count = len(books) - len(preview_paths)
        path_text = "\n".join(preview_paths)
        if extra_count > 0:
            path_text += f"\n... 以及另外 {extra_count} 项"
        answer = QMessageBox.question(
            self,
            "删除",
            f"从批量整理列表和数据库中删除选中的 {len(books)} 项？\n"
            f"{path_text}\n\n"
            "只会删除数据库记录和关联 novel_chapters / export_jobs，不会删除原始文件。",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        try:
            deleted_count = delete_books([int(book["id"]) for book in books])
            self.current_batch_book_id = None
        except Exception as exc:
            logger.exception("Failed to delete selected batch books")
            self._show_error(f"删除失败：{exc}")
            return

        self._refresh_batch_table()
        QMessageBox.information(self, "批量整理", f"已删除 {deleted_count} 个条目。")

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
            if _is_novel_db_book(book):
                novel_result = import_novel_txt(source_path)
                series_title, book_title, volume_number = _resolve_titles_from_novel_import(
                    source_path,
                    novel_result,
                )
                work = self._work_for_reparsed_novel_book(
                    int(book["work_id"]),
                    series_title,
                    novel_result,
                )
                update_book(
                    book_id,
                    work_id=int(work["id"]),
                    title=book_title,
                    volume_number=volume_number,
                    media_type="novel",
                    source_type="novel_txt",
                    page_count=0,
                    chapter_count=novel_result.chapter_count,
                    text_length=novel_result.text_length,
                    export_format="epub",
                    status="need_review",
                )
                self._replace_novel_chapters(book_id, novel_result)
            else:
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
                    media_type="comic",
                    source_type=import_result.source_type,
                    page_count=len(import_result.pages),
                    chapter_count=0,
                    text_length=0,
                    export_format="cbz",
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

    def _work_for_reparsed_novel_book(
        self,
        current_work_id: int,
        series_title: str,
        import_result: NovelImportResult,
    ) -> RowDict:
        existing = _find_work_by_title(series_title)
        if existing is not None:
            work_id = int(existing["id"])
        elif len(list_books_by_work(current_work_id)) <= 1:
            work_id = current_work_id
        else:
            work = create_work(title=series_title)
            work_id = int(work["id"])

        updated = update_work(
            work_id,
            title=series_title,
            author=import_result.author_guess,
            language_iso="zh",
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

        is_novel = _is_novel_db_book(book)
        self.current_batch_book_id = book_id
        self._clear_ai_suggestion_table()
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
        self._load_batch_cover_override(book)
        direction = str(book.get("manga_direction") or "rtl")
        index = self.batch_direction_combo.findText(direction)
        self.batch_direction_combo.setCurrentIndex(index if index >= 0 else 0)
        self.batch_translator_edit.setEnabled(not is_novel)
        self.batch_direction_combo.setEnabled(not is_novel)
        if is_novel:
            self.batch_direction_combo.setToolTip("轻小说导出 EPUB，不使用漫画阅读方向。")
            self._load_batch_chapters(book_id)
        else:
            self.batch_direction_combo.setToolTip("")
            self._load_batch_chapters(None)
        self._set_novel_chapter_widgets_visible(is_novel)

    def _load_batch_cover_override(self, book: RowDict) -> None:
        cover_value = str(book.get("cover_override_path") or "").strip()
        if cover_value:
            self.batch_cover_override_path = Path(cover_value)
            self.batch_cover_override_label.setText(cover_value)
            self._show_cover_file(self.batch_cover_preview_label, self.batch_cover_override_path)
        else:
            self.batch_cover_override_path = None
            self.batch_cover_override_label.setText("未选择")
            self.batch_cover_preview_label.clear()
            self.batch_cover_preview_label.setText("未选择封面")

    def _generate_ai_suggestion(self) -> None:
        book_id = self.current_batch_book_id
        if book_id is None:
            self._show_error("请先选择一个 book。")
            return
        try:
            config = load_ai_provider_config(_GuiAiRepository())
            provider = create_ai_provider(config)
            service = AiSuggestionService(_GuiAiRepository(), provider)
            service.generate_for_book(book_id)
            latest = list_latest_ai_suggestion_by_book(book_id)
            if latest is None:
                raise LightBookError("AI 建议已生成，但无法从数据库读取。")
            self.current_ai_suggestion_id = int(latest["id"])
            self._populate_ai_suggestion_table(latest)
            if self.ai_suggestion_table.rowCount() > 0:
                self.ai_status_label.setText("AI 建议已生成。请选择需要应用的字段。")
        except AiProviderConfigError:
            config = load_ai_provider_config(_GuiAiRepository())
            self._show_error(f"未配置 API Key，请设置环境变量 {config.api_key_env}。")
        except Exception as exc:
            logger.exception("Failed to generate AI suggestion")
            self.ai_status_label.setText(f"AI 建议生成失败：{exc}")
            self._show_error(f"AI 建议生成失败：{exc}")

    def _apply_selected_ai_fields(self) -> None:
        book_id = self.current_batch_book_id
        if book_id is None:
            self._show_error("请先选择一个 book。")
            return
        if self.current_ai_suggestion_id is None:
            self._show_error("请先生成 AI 建议。")
            return

        fields = self._selected_ai_fields()
        if not fields:
            QMessageBox.information(self, "AI 辅助", "没有勾选要应用的字段。")
            return

        try:
            config = load_ai_provider_config(_GuiAiRepository())
            provider = create_ai_provider(config)
            service = AiSuggestionService(_GuiAiRepository(), provider)
            service.apply_suggestion(book_id, self.current_ai_suggestion_id, fields)
        except Exception as exc:
            logger.exception("Failed to apply AI suggestion")
            self._show_error(f"应用 AI 建议失败：{exc}")
            return

        self._refresh_batch_table(selected_book_id=book_id)
        QMessageBox.information(self, "AI 辅助", "已应用选中字段。")

    def _ignore_ai_suggestion(self) -> None:
        self._clear_ai_suggestion_table()

    def _clear_ai_suggestion_table(self) -> None:
        self.current_ai_suggestion_id = None
        self.current_ai_suggestion_row = None
        self.ai_suggestion_table.setRowCount(0)
        self.ai_status_label.setText("AI 只提供建议，不会自动覆盖数据。")

    def _populate_ai_suggestion_table(self, suggestion: RowDict) -> None:
        parsed = _json_dict(suggestion.get("parsed_json"))
        self.current_ai_suggestion_row = suggestion
        self.ai_suggestion_table.setRowCount(0)
        row_index = 0
        for field_name, field_label, can_apply in AI_APPLY_FIELDS:
            current_value = self._current_ai_field_value(field_name)
            suggested_value = _display_ai_value(parsed.get(field_name))
            if not suggested_value and not current_value:
                continue

            self.ai_suggestion_table.insertRow(row_index)
            row_values = [
                field_label,
                current_value,
                suggested_value,
            ]
            for column_index, value in enumerate(row_values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, field_name)
                self.ai_suggestion_table.setItem(row_index, column_index, item)

            apply_item = QTableWidgetItem()
            if can_apply:
                apply_item.setFlags(
                    Qt.ItemFlag.ItemIsUserCheckable
                    | Qt.ItemFlag.ItemIsEnabled
                    | Qt.ItemFlag.ItemIsSelectable
                )
                apply_item.setCheckState(Qt.CheckState.Unchecked)
            else:
                apply_item.setText("暂不支持应用")
                apply_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            apply_item.setData(Qt.ItemDataRole.UserRole, field_name)
            self.ai_suggestion_table.setItem(row_index, 3, apply_item)
            row_index += 1

        if row_index == 0:
            self.ai_status_label.setText("AI 已返回，但没有可应用字段。请查看原始响应。")

    def _selected_ai_fields(self) -> list[str]:
        fields: list[str] = []
        for row in range(self.ai_suggestion_table.rowCount()):
            item = self.ai_suggestion_table.item(row, 3)
            if item is None or item.checkState() != Qt.CheckState.Checked:
                continue
            field_name = item.data(Qt.ItemDataRole.UserRole)
            if field_name is not None:
                fields.append(str(field_name))
        return fields

    def _current_ai_field_value(self, field_name: str) -> str:
        if field_name == "clean_title":
            return self.batch_series_title_edit.text()
        if field_name == "book_title":
            return self.batch_book_title_edit.text()
        if field_name == "volume_number":
            return self.batch_volume_number_edit.text()
        if field_name == "authors":
            return self.batch_author_edit.text()
        if field_name == "translators":
            return self.batch_translator_edit.text()
        if field_name == "summary":
            return self.batch_summary_edit.toPlainText()
        if field_name == "genres":
            return self.batch_genres_edit.text()
        if field_name == "tags":
            return self.batch_tags_edit.text()
        if field_name == "language_iso":
            return self.batch_language_edit.text()
        if field_name == "manga_direction":
            return self.batch_direction_combo.currentText()
        return ""

    def _show_ai_raw_response(self) -> None:
        suggestion = self.current_ai_suggestion_row
        if suggestion is None and self.current_ai_suggestion_id is not None:
            suggestion = get_ai_suggestion(self.current_ai_suggestion_id)
        if suggestion is None:
            QMessageBox.information(self, "AI 辅助", "当前没有 AI 建议。")
            return
        parsed_json = _json_dict(suggestion.get("parsed_json"))
        raw_response = str(suggestion.get("raw_response") or "")[:3000]
        parsed_text = json.dumps(parsed_json, ensure_ascii=False, indent=2)[:3000]
        message = f"Raw response（前 3000 字）：\n{raw_response}\n\nParsed JSON：\n{parsed_text}"
        QMessageBox.information(self, "AI 原始响应", message)

    def _search_cover_and_metadata(self) -> None:
        book_id = self.current_batch_book_id
        if book_id is None:
            self._show_error("请先选择一个 book。")
            return

        try:
            service = MetadataSearchService(_GuiAiRepository(), MockSearchProvider())
            candidates = service.search_for_book(book_id)
        except Exception as exc:
            logger.exception("Metadata search failed")
            self._show_error(f"搜索失败：{exc}")
            return

        if not candidates:
            QMessageBox.information(self, "搜索封面/资料", "未找到匹配结果。")
            return

        dialog = QMessageBox(self)
        dialog.setWindowTitle("搜索结果")
        dialog.setIcon(QMessageBox.Icon.Information)
        lines = [f"找到 {len(candidates)} 个结果：\n"]
        for i, c in enumerate(candidates, 1):
            lines.append(
                f"{i}. {c.title}  —  {c.source_name}\n"
                f"   作者：{', '.join(c.authors) if c.authors else '未知'}\n"
                f"   简介：{c.summary[:80]}{'...' if len(c.summary) > 80 else ''}\n"
                f"   分类：{', '.join(c.genres) if c.genres else '无'}\n"
                f"   标签：{', '.join(c.tags) if c.tags else '无'}\n"
            )
        dialog.setText("\n".join(lines))
        dialog.exec()

    def _set_novel_chapter_widgets_visible(self, visible: bool) -> None:
        for widget in (
            self.batch_chapter_label,
            self.batch_chapter_table,
            self.batch_chapter_title_label,
            self.batch_chapter_title_edit,
            self.batch_save_chapter_title_button,
            self.batch_preview_epub_button,
            self.batch_open_preview_epub_button,
            self.batch_chapter_preview_label,
            self.batch_chapter_preview_edit,
        ):
            widget.setVisible(visible)

    def _load_batch_chapters(self, book_id: int | None) -> None:
        self.batch_chapter_table.blockSignals(True)
        self.batch_chapter_table.setRowCount(0)
        self.batch_chapter_title_edit.clear()
        self.batch_chapter_preview_edit.clear()
        if book_id is not None:
            for row_index, chapter in enumerate(list_novel_chapters(book_id)):
                self.batch_chapter_table.insertRow(row_index)
                row_values = [
                    str(chapter.get("order_index") or row_index + 1),
                    str(chapter.get("title") or ""),
                    str(len(str(chapter.get("content") or ""))),
                ]
                for column_index, value in enumerate(row_values):
                    item = QTableWidgetItem(value)
                    item.setData(Qt.ItemDataRole.UserRole, int(chapter["id"]))
                    self.batch_chapter_table.setItem(row_index, column_index, item)
        self.batch_chapter_table.blockSignals(False)
        if self.batch_chapter_table.rowCount() > 0:
            self.batch_chapter_table.selectRow(0)
            self._on_chapter_selection_changed()

    def _selected_chapter_id(self) -> int | None:
        row = self.batch_chapter_table.currentRow()
        if row < 0:
            return None
        item = self.batch_chapter_table.item(row, 0)
        if item is None:
            return None
        chapter_id = item.data(Qt.ItemDataRole.UserRole)
        return int(chapter_id) if chapter_id is not None else None

    def _on_chapter_selection_changed(self) -> None:
        if self.current_batch_book_id is None:
            return
        chapter_id = self._selected_chapter_id()
        if chapter_id is None:
            self.batch_chapter_title_edit.clear()
            self.batch_chapter_preview_edit.clear()
            return
        for chapter in list_novel_chapters(self.current_batch_book_id):
            if int(chapter["id"]) == chapter_id:
                self.batch_chapter_title_edit.setText(str(chapter.get("title") or ""))
                self.batch_chapter_preview_edit.setPlainText(str(chapter.get("content") or ""))
                return

    def _save_selected_chapter_title(self, show_message: bool = True) -> bool:
        chapter_id = self._selected_chapter_id()
        if chapter_id is None:
            if show_message:
                self._show_error("请先选择一个章节。")
            return False
        title = self.batch_chapter_title_edit.text().strip() or "正文"
        try:
            update_novel_chapter_title(chapter_id, title)
        except Exception as exc:
            logger.exception("Failed to save novel chapter title")
            self._show_error(f"保存章节标题失败：{exc}")
            return False
        if self.current_batch_book_id is not None:
            self._load_batch_chapters(self.current_batch_book_id)
        if show_message:
            QMessageBox.information(self, "批量整理", "章节标题已保存。")
        return True

    def _generate_preview_epub(self) -> None:
        book_id = self.current_batch_book_id
        if book_id is None:
            self._show_error("请先选择一个 book。")
            return
        book = get_book(book_id)
        if book is None or not _is_novel_db_book(book):
            self._show_error("请先选择一个轻小说 book。")
            return
        if not self._save_batch_metadata(show_message=False):
            return
        if self._selected_chapter_id() is not None and not self._save_selected_chapter_title(show_message=False):
            return
        preview_path = _preview_epub_path(book_id)
        try:
            export_novel_preview_from_database(book_id, preview_path)
        except Exception as exc:
            logger.exception("Failed to generate preview EPUB")
            self._show_error(f"生成预览 EPUB 失败：{exc}")
            return
        QMessageBox.information(self, "批量整理", f"预览 EPUB 已生成：\n{preview_path}")

    def _open_preview_epub(self) -> None:
        book_id = self.current_batch_book_id
        if book_id is None:
            self._show_error("请先选择一个 book。")
            return
        preview_path = _preview_epub_path(book_id)
        if not preview_path.exists():
            self._show_error("请先生成预览 EPUB。")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(preview_path.resolve())))

    def _replace_novel_chapters(self, book_id: int, novel_result: NovelImportResult) -> None:
        delete_novel_chapters_by_book(book_id)
        order_index = 1
        for volume in novel_result.volumes:
            volume_title = str(getattr(volume, "title", "") or "")
            for chapter in getattr(volume, "chapters", []):
                chapter_title = str(getattr(chapter, "title", "") or "正文")
                title = f"{volume_title} {chapter_title}".strip() if volume_title else chapter_title
                create_novel_chapter(
                    book_id=book_id,
                    title=title,
                    content=str(getattr(chapter, "content", "") or ""),
                    order_index=order_index,
                )
                order_index += 1

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
        self.batch_translator_edit.setEnabled(True)
        self.batch_direction_combo.setEnabled(True)
        self.batch_direction_combo.setToolTip("")
        self.batch_cover_override_path = None
        self.batch_cover_override_label.setText("未选择")
        self.batch_cover_preview_label.clear()
        self.batch_cover_preview_label.setText("未选择封面")
        self._clear_ai_suggestion_table()
        self._load_batch_chapters(None)
        self._set_novel_chapter_widgets_visible(False)

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
            series_title = self.batch_series_title_edit.text().strip() or "未命名"
            book_title = self.batch_book_title_edit.text().strip() or series_title
            is_novel = _is_novel_db_book(book)
            cover_override_path = str(self.batch_cover_override_path or "")
            update_work(
                int(book["work_id"]),
                title=series_title,
                author=self.batch_author_edit.text().strip(),
                summary=self.batch_summary_edit.toPlainText().strip(),
                genres=self.batch_genres_edit.text().strip(),
                tags=self.batch_tags_edit.text().strip(),
                language_iso=self.batch_language_edit.text().strip() or "zh",
            )
            if is_novel:
                update_book(
                    self.current_batch_book_id,
                    title=book_title,
                    volume_number=volume_number,
                    media_type="novel",
                    source_type="novel_txt",
                    export_format="epub",
                    cover_override_path=cover_override_path,
                    status="ready",
                )
            else:
                update_book(
                    self.current_batch_book_id,
                    title=book_title,
                    volume_number=volume_number,
                    media_type="comic",
                    export_format="cbz",
                    cover_override_path=cover_override_path,
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
        book_ids = self._selected_batch_book_ids()
        if not book_ids:
            self._show_error("请先选择一个或多个 book。")
            return
        current_book_id = self._selected_batch_book_id()
        if current_book_id is not None and current_book_id in book_ids:
            self.current_batch_book_id = current_book_id
            if not self._save_batch_metadata(show_message=False):
                return
            book = get_book(current_book_id)
            if book is not None and _is_novel_db_book(book) and self._selected_chapter_id() is not None:
                if not self._save_selected_chapter_title(show_message=False):
                    return
        self._export_batch_books(book_ids)

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

        is_novel = _is_novel_db_book(book)
        try:
            output_path = export_book_from_database(book_id, self.output_root or Path("."))
            logger.info("Batch exported book %s to %s", book_id, output_path)
            return None
        except Exception as exc:
            logger.exception("Batch export failed for book %s", book_id)
            update_book(book_id, status="failed")
            return _format_export_error(book, exc, is_novel)

    def _import_result_for_book(self, book: RowDict) -> ImportResult:
        source_path = Path(str(book["source_path"]))
        source_type = str(book["source_type"])
        if source_type == "epub":
            return import_comic_epub(source_path)
        if source_type == "cbz":
            return import_cbz(source_path)
        if source_type == "image_folder":
            return import_image_folder(source_path)
        raise LightBookError(f"不支持的 source_type：{source_type}")

    def _metadata_for_batch_export(self, book: RowDict, work: RowDict) -> ComicMetadata:
        direction = str(book.get("manga_direction") or "rtl")
        if direction not in {"rtl", "ltr", "webtoon"}:
            direction = "rtl"

        return ComicMetadata(
            series_title=str(work.get("title") or "未命名"),
            book_title=str(book.get("title") or work.get("title") or "未命名"),
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


class _GuiAiRepository:
    def get_book(self, book_id: int) -> RowDict | None:
        return get_book(book_id)

    def get_work(self, work_id: int) -> RowDict | None:
        return get_work(work_id)

    def list_novel_chapters(self, book_id: int) -> list[RowDict]:
        return list_novel_chapters(book_id)

    def create_ai_suggestion(self, **kwargs: Any) -> RowDict:
        return create_ai_suggestion(**kwargs)

    def get_ai_suggestion(self, ai_suggestion_id: int) -> RowDict | None:
        return get_ai_suggestion(ai_suggestion_id)

    def update_work(self, work_id: int, **kwargs: Any) -> RowDict | None:
        return update_work(work_id, **kwargs)

    def update_book(self, book_id: int, **kwargs: Any) -> RowDict | None:
        return update_book(book_id, **kwargs)

    def get_setting(self, key: str) -> str | None:
        return get_setting(key)

    def set_setting(self, key: str, value: str) -> None:
        set_setting(key, value)


def _preview_epub_path(book_id: int) -> Path:
    return Path("data") / "previews" / str(book_id) / "preview.epub"


def _json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


def _display_ai_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _display_status(status: str) -> str:
    return {
        "need_review": "待确认",
        "ready": "可导出",
        "exported": "已导出",
        "failed": "失败",
        "pending": "等待中",
    }.get(status, status)


def _display_media_type(media_type: str) -> str:
    return {
        "comic": "漫画",
        "novel": "轻小说",
    }.get(media_type, media_type)


def _ai_api_key_status_text(api_key_env: str = "LIGHTBOOK_AI_API_KEY") -> str:
    if os.environ.get(api_key_env):
        return f"已从环境变量 {api_key_env} 读取（不会保存到项目）。"
    return f"未配置。需要真实 provider 时请设置环境变量 {api_key_env}。"


def _mask_api_key(api_key: str) -> str:
    if not api_key:
        return ""
    if len(api_key) <= 10:
        return "***"
    return f"{api_key[:6]}***{api_key[-4:]}"


def _flatten_novel_import_chapters(import_result: NovelImportResult) -> list[NovelChapter]:
    chapters: list[NovelChapter] = []
    order_index = 1
    for volume in import_result.volumes:
        volume_title = str(getattr(volume, "title", "") or "")
        for chapter in getattr(volume, "chapters", []):
            chapter_title = str(getattr(chapter, "title", "") or "正文")
            title = f"{volume_title} {chapter_title}".strip() if volume_title else chapter_title
            chapters.append(
                NovelChapter(
                    title=title,
                    content=str(getattr(chapter, "content", "") or ""),
                    order_index=order_index,
                )
            )
            order_index += 1
    return chapters


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
        or "未命名"
    )
    book_title = (
        parsed.book_title.strip()
        or metadata.book_title.strip()
        or metadata.series_title.strip()
        or series_title
    )
    return series_title, book_title, parsed.volume_number


def _resolve_titles_from_novel_import(
    source_path: Path,
    import_result: NovelImportResult,
) -> tuple[str, str, int | None]:
    series_title = import_result.title_guess.strip() or "未命名轻小说"
    first_volume = import_result.volumes[0] if import_result.volumes else None
    book_title = (
        (first_volume.title.strip() if first_volume else "")
        or sanitize_windows_filename(source_path.stem)
        or series_title
    )
    volume_number = first_volume.volume_number if first_volume else None
    return series_title, book_title, volume_number


def _is_novel_db_book(book: RowDict) -> bool:
    return (
        str(book.get("media_type") or "") == "novel"
        or str(book.get("export_format") or "") == "epub"
        or str(book.get("source_type") or "") == "novel_txt"
    )


def _book_media_type(book: RowDict) -> str:
    return "novel" if _is_novel_db_book(book) else "comic"


def _format_batch_error(error: str) -> str:
    if ".txt" in error.casefold() and _looks_like_decode_error(error):
        return f"TXT 解码失败：{error}"
    return error


def _format_export_error(book: RowDict, exc: Exception, is_novel: bool) -> str:
    source_path = str(book.get("source_path") or "")
    message = str(exc)
    if is_novel and _looks_like_decode_error(message):
        return f"TXT 解码失败：{source_path}: {message}"
    if is_novel:
        return f"EPUB 导出失败：{source_path}: {message}"
    return f"{source_path}: {message}"


def _looks_like_decode_error(value: str) -> bool:
    lowered = value.casefold()
    return "无法解码" in value or "decode" in lowered or "unicodedecodeerror" in lowered


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
