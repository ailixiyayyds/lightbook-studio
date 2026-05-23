from __future__ import annotations

import json
import logging
import os
import sys
from collections.abc import Callable
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, cast

from PySide6.QtCore import Qt
from PySide6.QtCore import QUrl
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
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
    QStackedWidget,
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

from app.core.cache_cleanup import cleanup_old_log_files, cleanup_unreferenced_cover_cache
from app.core.config import load_config, save_config
from app.core.local_secrets import get_secret, has_secret, set_secret
from app.core.logging_config import LOG_DIR, LOG_FILE
from app.core.models import ComicMetadata, ImportResult, LightBookError, MangaDirection
from app.ai.config import AiProviderConfig, get_api_key_from_env, load_ai_provider_config, save_ai_provider_config
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
from app.gui.metadata_search_dialog import MetadataSearchDialog
from app.gui.cache_binding import should_refresh_book_cache
from app.gui.widgets import set_comfortable_button_size
from app.search.config import SearchConfig, load_search_config, save_search_config
from app.search.provider_factory import create_metadata_search_provider
from app.search.types import MetadataSearchCandidate, MetadataSearchQuery
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
    create_ai_request_log,
    create_metadata_search_result,
    delete_all_ai_request_logs,
    delete_all_ai_suggestions,
    delete_all_metadata_search_results,
    delete_ai_request_logs_by_book,
    delete_ai_suggestions_by_book,
    delete_metadata_search_results_by_book,
    get_ai_suggestion,
    get_latest_metadata_search_result_by_book,
    list_latest_ai_suggestion_by_book,
    list_ai_request_logs,
    list_ai_request_logs_by_book,
    list_metadata_search_results_by_book,
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
        self.resize(1700, 980)
        self.setMinimumSize(1280, 760)

        self.config = load_config()
        self._running_tasks: set[str] = set()
        self._running_book_tasks: set[tuple[str, int]] = set()
        self._active_handles: dict[str, object] = {}
        self._active_tasks: dict[str, object] = self._active_handles
        self.import_result: ImportResult | None = None
        self.novel_import_result: NovelImportResult | None = None
        self.single_cover_override_path: Path | None = None
        self.batch_cover_override_path: Path | None = None
        self.output_root = Path(self.config.recent_output_dir) if self.config.recent_output_dir else None
        self.current_book_id: int | None = None
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

        # Single import AI widgets
        self.single_ai_generate_button = QPushButton("生成 AI 建议")
        self.single_ai_generate_button.clicked.connect(self._generate_single_ai_suggestion)
        self.single_ai_apply_button = QPushButton("应用选中字段")
        self.single_ai_apply_button.clicked.connect(self._apply_single_ai_fields)
        self.single_ai_raw_button = QPushButton("查看原始响应")
        self.single_ai_raw_button.clicked.connect(self._show_single_ai_raw_response)
        self.single_ai_search_button = QPushButton("搜索封面/资料")
        self.single_ai_search_button.clicked.connect(self._search_single_cover)
        self.single_ai_manual_cover_edit = QLineEdit()
        self.single_ai_manual_cover_edit.setPlaceholderText("粘贴图片 URL 下载封面…")
        self.single_ai_manual_cover_btn = QPushButton("下载封面")
        self.single_ai_manual_cover_btn.clicked.connect(self._single_manual_cover_download)
        self.single_ai_status_label = QLabel("请先保存到库，再使用 AI 建议和封面搜索。")
        self.single_ai_suggestion_table = QTableWidget(0, 4)
        self.single_ai_suggestion_table.setHorizontalHeaderLabels(["字段", "当前值", "AI 建议", "应用"])
        self.single_ai_suggestion_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.single_ai_suggestion_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.single_ai_suggestion_table.setMinimumHeight(220)
        self.single_ai_suggestion_table.verticalHeader().setVisible(False)
        self.single_ai_suggestion_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.single_ai_suggestion_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._set_single_ai_enabled(False)
        self.single_saved_book_id: int | None = None
        self.single_ai_suggestion_id: int | None = None
        self.single_ai_suggestion_row: RowDict | None = None

    def _create_batch_widgets(self) -> None:
        self.batch_table = QTableWidget(0, len(BATCH_TABLE_COLUMNS))
        self.batch_table.setHorizontalHeaderLabels(BATCH_TABLE_COLUMNS)
        self.batch_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.batch_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.batch_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.batch_table.verticalHeader().setVisible(False)
        self.batch_table.verticalHeader().setDefaultSectionSize(30)
        self.batch_table.setMinimumWidth(620)
        self.batch_table.setAlternatingRowColors(True)
        self.batch_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.batch_table.setColumnWidth(0, 70)
        self.batch_table.setColumnWidth(1, 90)
        self.batch_table.setColumnWidth(3, 60)
        self.batch_table.setColumnWidth(4, 90)
        self.batch_table.setColumnWidth(5, 180)
        self.batch_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
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
        self.batch_summary_edit.setMinimumHeight(160)
        self.batch_summary_edit.setMaximumHeight(220)
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
        self.batch_download_cover_button = QPushButton("从图片链接下载封面")
        self.batch_download_cover_button.clicked.connect(
            lambda: self._prompt_manual_cover_from_search(self.current_batch_book_id)
        )
        self.batch_cover_preview_label = QLabel()
        self.batch_cover_preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.batch_cover_preview_label.setText("未选择封面")
        self.batch_cover_preview_label.setMinimumSize(260, 360)
        self.batch_cover_preview_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.batch_cover_preview_label.setStyleSheet("border: 1px solid #cccccc; background: #fafafa;")

        self.batch_chapter_label = QLabel("章节列表")
        self.batch_chapter_table = QTableWidget(0, 3)
        self.batch_chapter_table.setHorizontalHeaderLabels(["序号", "章节标题", "字数"])
        self.batch_chapter_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.batch_chapter_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.batch_chapter_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.batch_chapter_table.setMinimumHeight(300)
        self.batch_chapter_table.verticalHeader().setDefaultSectionSize(28)
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
        self.batch_chapter_preview_edit.setMinimumHeight(240)

        self.ai_generate_button = QPushButton("生成 AI 建议")
        self.ai_generate_button.clicked.connect(self._generate_ai_suggestion)
        self.ai_apply_button = QPushButton("应用选中字段")
        self.ai_apply_button.clicked.connect(self._apply_selected_ai_fields)
        self.ai_ignore_button = QPushButton("忽略建议")
        self.ai_ignore_button.clicked.connect(self._ignore_ai_suggestion)
        self.ai_select_all_button = QPushButton("全选建议")
        self.ai_select_all_button.clicked.connect(lambda: self._set_ai_apply_checks(True))
        self.ai_select_none_button = QPushButton("全不选")
        self.ai_select_none_button.clicked.connect(lambda: self._set_ai_apply_checks(False))
        self.ai_select_empty_button = QPushButton("只选空字段")
        self.ai_select_empty_button.clicked.connect(self._select_empty_ai_fields)
        self.ai_raw_response_button = QPushButton("查看原始响应")
        self.ai_raw_response_button.clicked.connect(self._show_ai_raw_response)
        self.ai_search_button = QPushButton("搜索封面/资料")
        self.ai_search_button.clicked.connect(self._search_cover_and_metadata)
        self.search_status_label = QLabel("尚未搜索封面/资料。")
        self.search_view_cache_button = QPushButton("查看搜索结果")
        self.search_view_cache_button.clicked.connect(self._show_cached_search_result)
        self.search_clear_cache_button = QPushButton("清除本书搜索缓存")
        self.search_clear_cache_button.clicked.connect(self._clear_current_book_search_cache)
        self.ai_status_label = QLabel("AI 只提供建议，不会自动覆盖数据。")
        self.ai_suggestion_table = QTableWidget(0, 4)
        self.ai_suggestion_table.setHorizontalHeaderLabels(["字段", "当前值", "AI 建议", "应用"])
        self.ai_suggestion_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.ai_suggestion_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.ai_suggestion_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.ai_suggestion_table.setMinimumHeight(420)
        self.ai_suggestion_table.verticalHeader().setDefaultSectionSize(32)
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

        self.search_provider_label = QLabel("AI")
        self.search_provider_combo = QComboBox()
        self.search_provider_combo.addItem("AI 资料搜索（推荐）", "ai")
        self.search_provider_combo.addItem("Mock（仅测试）", "mock")
        self.search_enabled_check = QCheckBox("启用联网搜索")
        self.search_enabled_check.setChecked(True)
        self.search_timeout_spin = QSpinBox()
        self.search_timeout_spin.setRange(5, 60)
        self.search_max_candidates_spin = QSpinBox()
        self.search_max_candidates_spin.setRange(1, 20)
        self.search_max_detail_pages_spin = QSpinBox()
        self.search_max_detail_pages_spin.setRange(0, 8)
        self.search_ai_query_planner_check = QCheckBox("启用 AI Query Planner")
        self.search_ai_content_extraction_check = QCheckBox("启用 AI 内容抽取")
        self.search_content_extract_max_chars_spin = QSpinBox()
        self.search_content_extract_max_chars_spin.setRange(1000, 40000)
        self.search_content_extract_max_chars_spin.setSingleStep(1000)
        self.search_content_extract_top_n_spin = QSpinBox()
        self.search_content_extract_top_n_spin.setRange(1, 10)
        self.search_bangumi_enabled_check = QCheckBox("启用 Bangumi")
        self.search_bangumi_base_url_edit = QLineEdit()
        self.search_bangumi_user_agent_edit = QLineEdit()
        self.search_bangumi_timeout_spin = QSpinBox()
        self.search_bangumi_timeout_spin.setRange(1, 60)
        self.search_bangumi_max_queries_spin = QSpinBox()
        self.search_bangumi_max_queries_spin.setRange(1, 12)
        self.search_moegirl_enabled_check = QCheckBox("启用萌娘百科")
        self.search_moegirl_api_url_edit = QLineEdit()
        self.search_moegirl_user_agent_edit = QLineEdit()
        self.search_moegirl_parse_check = QCheckBox("启用 parse API")
        self.search_moegirl_wikitext_check = QCheckBox("启用 wikitext fallback")
        self.search_moegirl_html_check = QCheckBox("允许同站 HTML fallback（默认关闭）")
        self.search_moegirl_max_detail_spin = QSpinBox()
        self.search_moegirl_max_detail_spin.setRange(1, 20)
        self.search_moegirl_timeout_spin = QSpinBox()
        self.search_moegirl_timeout_spin.setRange(1, 60)
        self.search_google_enabled_check = QCheckBox("启用 Google Books")
        self.search_google_key_env_edit = QLineEdit()
        self.search_google_key_edit = QLineEdit()
        self.search_google_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.search_google_key_status_label = QLabel("")
        self.search_google_timeout_spin = QSpinBox()
        self.search_google_timeout_spin.setRange(1, 60)
        self.search_google_cooldown_spin = QSpinBox()
        self.search_google_cooldown_spin.setRange(1, 120)
        self.search_ndl_enabled_check = QCheckBox("启用 NDL")
        self.search_ndl_base_url_edit = QLineEdit()
        self.search_ndl_timeout_spin = QSpinBox()
        self.search_ndl_timeout_spin.setRange(1, 60)
        self.search_open_library_enabled_check = QCheckBox("启用 Open Library")
        self.search_open_library_base_url_edit = QLineEdit()
        self.search_open_library_timeout_spin = QSpinBox()
        self.search_open_library_timeout_spin.setRange(1, 60)
        self.search_generic_provider_combo = QComboBox()
        for label, value in [
            ("disabled", "disabled"),
            ("brave", "brave"),
            ("bing", "bing"),
            ("serpapi", "serpapi"),
            ("tavily", "tavily"),
        ]:
            self.search_generic_provider_combo.addItem(label, value)
        self.search_generic_endpoint_edit = QLineEdit()
        self.search_generic_key_env_edit = QLineEdit()
        self.search_generic_key_edit = QLineEdit()
        self.search_generic_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.search_generic_key_status_label = QLabel("")
        self.search_amazon_jp_enabled_check = QCheckBox("启用 Amazon JP 官方 API（不会爬 HTML）")
        self.search_test_button = QPushButton("测试搜索配置")
        self.search_test_button.clicked.connect(self._test_search_settings)
        self._load_search_settings_into_widgets()

        self.settings_output_label = QLabel("未选择")

    def _build_ui(self) -> None:
        self._build_menu_bar()
        tabs = QTabWidget()
        tabs.addTab(self._build_batch_tab(), "书库整理")
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
                padding: 6px 16px;
                font-size: 13px;
                min-height: 34px;
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
                min-height: 32px;
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
                min-height: 32px;
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
                min-height: 30px;
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
        self.menuBar().hide()

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
        save_to_lib_button = QPushButton("保存到库")
        save_to_lib_button.clicked.connect(self._save_single_to_library)
        export_button = QPushButton("导出")
        export_button.clicked.connect(self._export)

        top_buttons = QHBoxLayout()
        top_buttons.addWidget(choose_folder_button)
        top_buttons.addWidget(choose_file_button)
        top_buttons.addWidget(choose_output_button)
        top_buttons.addWidget(save_to_lib_button)
        top_buttons.addStretch()
        top_buttons.addWidget(export_button)

        info_form = QFormLayout()
        info_form.setSpacing(8)
        info_form.addRow("来源路径", self.source_label)
        info_form.addRow("输出目录", self.output_label)
        info_form.addRow("页数", self.page_count_label)
        info_form.addRow("警告", self.warning_box)
        info_form.addRow("文件列表前 20 项", self.file_list)

        metadata_form = QFormLayout()
        metadata_form.setSpacing(8)
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

        # Single import AI area
        single_ai_buttons = QHBoxLayout()
        single_ai_buttons.addWidget(self.single_ai_generate_button)
        single_ai_buttons.addWidget(self.single_ai_apply_button)
        single_ai_buttons.addWidget(self.single_ai_raw_button)
        single_ai_buttons.addWidget(self.single_ai_search_button)

        single_ai_manual_layout = QHBoxLayout()
        single_ai_manual_layout.addWidget(self.single_ai_manual_cover_edit)
        single_ai_manual_layout.addWidget(self.single_ai_manual_cover_btn)

        single_ai_group = QGroupBox("AI 辅助")
        single_ai_layout = QVBoxLayout()
        single_ai_layout.addLayout(single_ai_buttons)
        single_ai_layout.addWidget(self.single_ai_status_label)
        single_ai_layout.addWidget(self.single_ai_suggestion_table)
        single_ai_layout.addLayout(single_ai_manual_layout)
        single_ai_group.setLayout(single_ai_layout)

        form_container = QWidget()
        form_container_layout = QVBoxLayout()
        form_container_layout.setSpacing(10)
        form_container_layout.addLayout(top_buttons)
        form_container_layout.addLayout(content)
        form_container_layout.addWidget(single_ai_group)
        form_container_layout.addStretch()
        form_container.setLayout(form_container_layout)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(form_container)

        outer = QVBoxLayout()
        outer.addWidget(scroll)

        container = QWidget()
        container.setLayout(outer)
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
        select_all_button = QPushButton("全选")
        select_all_button.clicked.connect(self.batch_table.selectAll)
        clear_selection_button = QPushButton("清除选择")
        clear_selection_button.clicked.connect(self.batch_table.clearSelection)
        delete_selected_button = QPushButton("删除选中项")
        delete_selected_button.clicked.connect(self._delete_selected_batch_books)
        mark_ready_button = QPushButton("标记可导出")
        mark_ready_button.clicked.connect(lambda: self._mark_selected_batch_books("ready"))
        mark_need_review_button = QPushButton("标记待确认")
        mark_need_review_button.clicked.connect(lambda: self._mark_selected_batch_books("need_review"))
        batch_ai_menu_button = QPushButton("AI 批量操作")
        batch_ai_menu = QMenu(batch_ai_menu_button)
        batch_ai_menu.addAction("生成 AI 建议", lambda: self._batch_generate_ai_suggestions(apply=False))
        batch_ai_menu.addAction("生成并应用 AI 建议", lambda: self._batch_generate_ai_suggestions(apply=True))
        batch_ai_menu.addSeparator()
        batch_ai_menu.addAction("搜索封面/资料", lambda: self._batch_search_metadata(apply=False))
        batch_ai_menu.addAction("搜索并应用资料", lambda: self._batch_search_metadata(apply=True))
        batch_ai_menu_button.setMenu(batch_ai_menu)
        for button in (
            import_files_button,
            import_folders_button,
            scan_sources_button,
            refresh_button,
            select_all_button,
            clear_selection_button,
            delete_selected_button,
            mark_ready_button,
            mark_need_review_button,
            batch_ai_menu_button,
        ):
            set_comfortable_button_size(button)

        import_buttons = QHBoxLayout()
        import_buttons.setContentsMargins(0, 0, 0, 0)
        import_buttons.setSpacing(8)
        import_buttons.addWidget(import_files_button)
        import_buttons.addWidget(import_folders_button)
        import_buttons.addWidget(scan_sources_button)
        import_buttons.addStretch()
        import_buttons.addWidget(refresh_button)

        list_action_buttons = QHBoxLayout()
        list_action_buttons.setContentsMargins(0, 0, 0, 0)
        list_action_buttons.setSpacing(8)
        list_action_buttons.addWidget(mark_ready_button)
        list_action_buttons.addWidget(mark_need_review_button)
        list_action_buttons.addWidget(select_all_button)
        list_action_buttons.addWidget(clear_selection_button)
        list_action_buttons.addWidget(delete_selected_button)
        list_action_buttons.addWidget(batch_ai_menu_button)
        list_action_buttons.addStretch()

        self.detail_tabs = QTabWidget()
        self.detail_tabs.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.detail_tabs.addTab(self._build_basic_info_tab(), "基本信息")
        self.detail_tabs.addTab(self._build_chapter_tab(), "章节 / 正文")
        self.detail_tabs.addTab(self._build_ai_tab(), "AI 建议")
        self.detail_tabs.addTab(self._build_cover_search_tab(), "封面 / 资料搜索")
        self.detail_tabs.addTab(self._build_export_cache_tab(), "导出 / 缓存")
        self.detail_tabs.currentChanged.connect(self._save_splitter_sizes)

        tab_index_raw = get_setting("ui_detail_current_tab")
        if tab_index_raw is not None:
            try:
                idx = int(tab_index_raw)
                if 0 <= idx < self.detail_tabs.count():
                    self.detail_tabs.setCurrentIndex(idx)
            except (ValueError, TypeError):
                pass

        splitter = QSplitter(Qt.Orientation.Horizontal)

        list_panel = QWidget()
        list_layout = QVBoxLayout()
        list_layout.setContentsMargins(8, 8, 8, 8)
        list_layout.setSpacing(8)
        list_layout.addLayout(import_buttons)
        list_layout.addLayout(list_action_buttons)
        list_layout.addWidget(self.batch_table, stretch=1)
        list_panel.setLayout(list_layout)
        list_panel.setMinimumWidth(560)
        list_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        detail_panel = QWidget()
        detail_layout = QVBoxLayout()
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.setSpacing(0)
        detail_layout.addWidget(self.detail_tabs)
        detail_panel.setLayout(detail_layout)
        detail_panel.setMinimumWidth(680)
        detail_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        splitter.addWidget(list_panel)
        splitter.addWidget(detail_panel)
        splitter.setSizes(
            _splitter_sizes_from_setting(
                "ui_main_splitter_sizes",
                [765, 935],
                minimums=[560, 680],
            )
        )
        splitter.setChildrenCollapsible(False)
        splitter.setStretchFactor(0, 9)
        splitter.setStretchFactor(1, 11)
        splitter.splitterMoved.connect(self._save_splitter_sizes)
        self.main_splitter = splitter

        root = QVBoxLayout()
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)
        root.addWidget(splitter)

        container = QWidget()
        container.setLayout(root)
        return container

    def _build_basic_info_tab(self) -> QWidget:
        form = QFormLayout()
        form.setContentsMargins(12, 12, 12, 12)
        form.setSpacing(8)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form.addRow(_form_label("作品名"), self.batch_series_title_edit)
        form.addRow(_form_label("本卷标题"), self.batch_book_title_edit)
        form.addRow(_form_label("卷号"), self.batch_volume_number_edit)
        form.addRow(_form_label("作者"), self.batch_author_edit)
        form.addRow(_form_label("译者 / 汉化组"), self.batch_translator_edit)
        form.addRow(_form_label("简介"), self.batch_summary_edit)
        form.addRow(_form_label("分类"), self.batch_genres_edit)
        form.addRow(_form_label("标签"), self.batch_tags_edit)
        form.addRow(_form_label("语言"), self.batch_language_edit)
        form.addRow(_form_label("阅读方向"), self.batch_direction_combo)

        save_button = QPushButton("保存修改")
        save_button.clicked.connect(lambda: self._save_batch_metadata())

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addLayout(form)
        layout.addWidget(save_button)
        layout.addStretch()

        form_widget = QWidget()
        form_widget.setLayout(layout)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(form_widget)
        return scroll

    def _build_chapter_tab(self) -> QWidget:
        no_chapter_widget = QWidget()
        no_chapter_layout = QVBoxLayout()
        no_chapter_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        no_chapter_label = QLabel("当前条目不是轻小说，无章节内容。")
        no_chapter_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        no_chapter_label.setStyleSheet("font-size: 15px; color: #888; padding: 40px;")
        no_chapter_layout.addStretch()
        no_chapter_layout.addWidget(no_chapter_label)
        no_chapter_layout.addStretch()
        no_chapter_widget.setLayout(no_chapter_layout)

        chapter_widget = QWidget()
        chapter_layout = QVBoxLayout()
        chapter_layout.setContentsMargins(10, 10, 10, 10)
        chapter_layout.setSpacing(6)

        chapter_top = QWidget()
        chapter_top_layout = QVBoxLayout()
        chapter_top_layout.setContentsMargins(0, 0, 0, 0)
        chapter_top_layout.setSpacing(6)
        chapter_top_layout.addWidget(self.batch_chapter_label)
        chapter_top_layout.addWidget(self.batch_chapter_table, stretch=1)
        chapter_top_layout.addWidget(self.batch_chapter_title_label)
        chapter_top_layout.addWidget(self.batch_chapter_title_edit)
        chapter_title_buttons = QHBoxLayout()
        chapter_title_buttons.setSpacing(8)
        chapter_title_buttons.addWidget(self.batch_save_chapter_title_button)
        chapter_title_buttons.addWidget(self.batch_preview_epub_button)
        chapter_title_buttons.addWidget(self.batch_open_preview_epub_button)
        chapter_title_buttons.addStretch()
        chapter_top_layout.addLayout(chapter_title_buttons)
        chapter_top.setLayout(chapter_top_layout)

        chapter_bottom = QWidget()
        chapter_bottom_layout = QVBoxLayout()
        chapter_bottom_layout.setContentsMargins(0, 0, 0, 0)
        chapter_bottom_layout.setSpacing(4)
        chapter_bottom_layout.addWidget(self.batch_chapter_preview_label)
        chapter_bottom_layout.addWidget(self.batch_chapter_preview_edit, stretch=1)
        chapter_bottom.setLayout(chapter_bottom_layout)

        self.chapter_splitter = QSplitter(Qt.Orientation.Vertical)
        self.chapter_splitter.addWidget(chapter_top)
        self.chapter_splitter.addWidget(chapter_bottom)
        self.chapter_splitter.setChildrenCollapsible(False)
        self.chapter_splitter.setSizes(
            _splitter_sizes_from_setting(
                "ui_chapter_splitter_sizes",
                [360, 300],
                minimums=[300, 240],
            )
        )
        self.chapter_splitter.setStretchFactor(0, 5)
        self.chapter_splitter.setStretchFactor(1, 4)
        self.chapter_splitter.splitterMoved.connect(self._save_splitter_sizes)

        chapter_layout.addWidget(self.chapter_splitter)
        chapter_widget.setLayout(chapter_layout)

        self.chapter_stack = QStackedWidget()
        self.chapter_stack.addWidget(no_chapter_widget)
        self.chapter_stack.addWidget(chapter_widget)
        return self.chapter_stack

    def _build_ai_tab(self) -> QWidget:
        ai_buttons_top = QHBoxLayout()
        ai_buttons_top.setSpacing(8)
        ai_buttons_top.addWidget(self.ai_generate_button)
        ai_buttons_top.addWidget(self.ai_apply_button)
        ai_buttons_top.addWidget(self.ai_select_all_button)
        ai_buttons_top.addWidget(self.ai_select_none_button)
        ai_buttons_top.addWidget(self.ai_select_empty_button)
        ai_buttons_top.addStretch()

        ai_buttons_bottom = QHBoxLayout()
        ai_buttons_bottom.setSpacing(8)
        ai_buttons_bottom.addWidget(self.ai_raw_response_button)
        ai_buttons_bottom.addWidget(self.ai_ignore_button)
        self.ai_select_title_summary_btn = QPushButton("只选标题/简介/分类标签")
        self.ai_select_title_summary_btn.clicked.connect(self._select_title_summary_genre_ai_fields)
        ai_buttons_bottom.addWidget(self.ai_select_title_summary_btn)
        ai_view_logs_btn = QPushButton("查看 AI 请求日志")
        ai_view_logs_btn.clicked.connect(
            lambda: self._show_current_book_ai_logs()
            if self.current_book_id
            else self._show_error("请先选择一个 book。")
        )
        ai_buttons_bottom.addWidget(ai_view_logs_btn)
        ai_buttons_bottom.addStretch()

        ai_bottom = QHBoxLayout()
        ai_bottom.setSpacing(8)
        ai_bottom.addWidget(self.ai_status_label, stretch=1)
        ai_clear_cache_btn = QPushButton("清除本书 AI 建议缓存")
        ai_clear_cache_btn.clicked.connect(self._clear_current_book_ai_cache)
        ai_bottom.addWidget(ai_clear_cache_btn)

        layout = QVBoxLayout()
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        layout.addLayout(ai_buttons_top)
        layout.addLayout(ai_buttons_bottom)
        layout.addWidget(self.ai_suggestion_table, stretch=1)
        layout.addLayout(ai_bottom)

        tab = QWidget()
        tab.setLayout(layout)
        return tab

    def _build_cover_search_tab(self) -> QWidget:
        cover_panel = QWidget()
        cover_layout = QVBoxLayout()
        cover_layout.setContentsMargins(10, 10, 10, 10)
        cover_layout.setSpacing(8)
        cover_title = QLabel("封面预览")
        cover_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cover_layout.addWidget(cover_title)
        cover_layout.addWidget(self.batch_cover_preview_label, alignment=Qt.AlignmentFlag.AlignHCenter)
        cover_layout.addWidget(self.batch_cover_override_label)
        batch_cover_buttons = QHBoxLayout()
        batch_cover_buttons.setSpacing(8)
        batch_cover_buttons.addWidget(self.batch_choose_cover_button)
        batch_cover_buttons.addWidget(self.batch_clear_cover_button)
        batch_cover_buttons.addWidget(self.batch_download_cover_button)
        cover_layout.addLayout(batch_cover_buttons)
        cover_layout.addStretch()
        cover_panel.setLayout(cover_layout)
        cover_panel.setMinimumSize(260, 360)

        search_panel = QWidget()
        search_layout = QVBoxLayout()
        search_layout.setContentsMargins(10, 10, 10, 10)
        search_layout.setSpacing(8)

        search_buttons = QHBoxLayout()
        search_buttons.setSpacing(8)
        search_buttons.addWidget(self.ai_search_button)
        search_buttons.addWidget(self.search_view_cache_button)
        self.search_redo_button = QPushButton("重新搜索")
        self.search_redo_button.clicked.connect(self._search_cover_and_metadata)
        search_buttons.addWidget(self.search_redo_button)
        search_buttons.addStretch()

        search_cache_buttons = QHBoxLayout()
        search_cache_buttons.setSpacing(8)
        search_cache_buttons.addWidget(self.search_clear_cache_button)
        search_cache_buttons.addStretch()

        search_layout.addLayout(search_buttons)
        search_layout.addWidget(self.search_status_label)
        search_layout.addLayout(search_cache_buttons)
        self.search_diag_label = QLabel("")
        self.search_diag_label.setWordWrap(True)
        self.search_diag_label.setStyleSheet("color: #666; font-size: 12px;")
        search_layout.addWidget(self.search_diag_label)
        search_layout.addStretch()

        search_panel.setLayout(search_layout)
        search_panel.setMinimumWidth(400)

        self.cover_search_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.cover_search_splitter.addWidget(cover_panel)
        self.cover_search_splitter.addWidget(search_panel)
        self.cover_search_splitter.setChildrenCollapsible(False)
        self.cover_search_splitter.setSizes(
            _splitter_sizes_from_setting(
                "ui_cover_search_splitter_sizes",
                [300, 520],
                minimums=[260, 400],
            )
        )
        self.cover_search_splitter.setStretchFactor(0, 3)
        self.cover_search_splitter.setStretchFactor(1, 5)
        self.cover_search_splitter.splitterMoved.connect(self._save_splitter_sizes)

        return self.cover_search_splitter

    def _build_export_cache_tab(self) -> QWidget:
        self.export_output_label = QLabel("未选择")
        self.export_output_label.setWordWrap(True)

        export_group = QGroupBox("导出操作")
        export_layout = QVBoxLayout()
        export_layout.setSpacing(8)
        export_path_row = QHBoxLayout()
        export_path_row.addWidget(QLabel("输出路径:"))
        export_path_row.addWidget(self.export_output_label, stretch=1)
        export_layout.addLayout(export_path_row)
        export_buttons_row = QHBoxLayout()
        export_buttons_row.setSpacing(8)
        export_selected_btn = QPushButton("导出选中项")
        export_selected_btn.clicked.connect(self._export_selected_batch_book)
        export_ready_btn = QPushButton("导出全部 ready")
        export_ready_btn.clicked.connect(self._export_all_ready_books)
        export_buttons_row.addWidget(export_selected_btn)
        export_buttons_row.addWidget(export_ready_btn)
        export_buttons_row.addStretch()
        export_layout.addLayout(export_buttons_row)
        self.export_status_label = QLabel("")
        export_layout.addWidget(self.export_status_label)
        export_group.setLayout(export_layout)

        book_cache_group = QGroupBox("当前条目缓存")
        book_cache_layout = QVBoxLayout()
        book_cache_layout.setSpacing(8)
        book_cache_buttons = QHBoxLayout()
        book_cache_buttons.setSpacing(8)
        clear_book_ai_btn = QPushButton("清除本书 AI 建议缓存")
        clear_book_ai_btn.clicked.connect(self._clear_current_book_ai_cache)
        clear_book_search_btn = QPushButton("清除本书搜索结果缓存")
        clear_book_search_btn.clicked.connect(self._clear_current_book_search_cache)
        clear_book_logs_btn = QPushButton("清除本书 AI 请求日志")
        clear_book_logs_btn.clicked.connect(lambda: (
            delete_ai_request_logs_by_book(self.current_book_id)
            if self.current_book_id and QMessageBox.question(
                self, "清除日志", "清除当前书 AI 请求日志？"
            ) == QMessageBox.StandardButton.Yes
            else None
        ))
        book_cache_buttons.addWidget(clear_book_ai_btn)
        book_cache_buttons.addWidget(clear_book_search_btn)
        book_cache_buttons.addWidget(clear_book_logs_btn)
        book_cache_buttons.addStretch()
        book_cache_layout.addLayout(book_cache_buttons)
        book_cache_group.setLayout(book_cache_layout)

        global_cache_group = QGroupBox("全局缓存与日志")
        global_cache_layout = QVBoxLayout()
        global_cache_layout.setSpacing(8)
        global_buttons = QHBoxLayout()
        global_buttons.setSpacing(8)
        clear_unref_covers_btn = QPushButton("清理未引用封面缓存")
        clear_unref_covers_btn.clicked.connect(self._clear_unreferenced_cover_cache)
        open_data_btn = QPushButton("打开数据目录")
        open_data_btn.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(Path("data").resolve()))))
        open_log_dir_btn = QPushButton("打开日志目录")
        open_log_dir_btn.clicked.connect(self._open_log_dir)
        open_log_file_btn = QPushButton("打开日志文件")
        open_log_file_btn.clicked.connect(self._open_log_file)
        global_buttons.addWidget(clear_unref_covers_btn)
        global_buttons.addWidget(open_data_btn)
        global_buttons.addWidget(open_log_dir_btn)
        global_buttons.addWidget(open_log_file_btn)
        global_buttons.addStretch()
        global_cache_layout.addLayout(global_buttons)
        global_cache_group.setLayout(global_cache_layout)

        layout = QVBoxLayout()
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(12)
        layout.addWidget(export_group)
        layout.addWidget(book_cache_group)
        layout.addWidget(global_cache_group)
        layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        scroll_widget.setLayout(layout)
        scroll.setWidget(scroll_widget)
        return scroll

    def _build_settings_tab(self) -> QWidget:
        choose_output_button = QPushButton("选择输出目录")
        choose_output_button.clicked.connect(self._choose_output)

        # Output section
        output_group = QGroupBox("输出设置")
        output_form = QFormLayout()
        output_form.setSpacing(8)
        output_form.addRow("输出目录", self.settings_output_label)
        output_form.addRow("", choose_output_button)
        output_group.setLayout(output_form)

        # AI section
        ai_group = QGroupBox("AI 设置")
        ai_form = QFormLayout()
        ai_form.setSpacing(8)
        ai_form.addRow("Provider 类型", self.ai_provider_combo)
        ai_form.addRow("AI base_url", self.ai_base_url_edit)
        ai_form.addRow("AI model", self.ai_model_edit)
        ai_form.addRow("API Key 环境变量名", self.ai_api_key_env_edit)
        ai_form.addRow("Timeout 秒数", self.ai_timeout_spin)
        ai_form.addRow("Temperature", self.ai_temperature_spin)
        ai_form.addRow("说明", self.ai_settings_hint_label)
        ai_btn_layout = QHBoxLayout()
        ai_btn_layout.addWidget(self.ai_save_settings_button)
        ai_btn_layout.addWidget(self.ai_test_connection_button)
        ai_form.addRow("", ai_btn_layout)
        ai_form.addRow("AI api_key 状态", self.ai_api_key_status_label)
        ai_form.addRow("AI 诊断", self.ai_diagnostic_label)
        ai_group.setLayout(ai_form)

        # Search section
        search_group = QGroupBox("搜索设置")
        search_form = QFormLayout()
        search_form.setSpacing(8)
        search_form.addRow("搜索 provider", self.search_provider_combo)
        search_form.addRow("启用联网搜索", self.search_enabled_check)
        search_form.addRow("搜索超时秒数", self.search_timeout_spin)
        search_form.addRow("最多搜索结果", self.search_max_candidates_spin)
        search_form.addRow("最多详情页面", self.search_max_detail_pages_spin)
        search_form.addRow("AI Query Planner", self.search_ai_query_planner_check)
        search_form.addRow("AI 内容抽取", self.search_ai_content_extraction_check)
        search_form.addRow("抽取最大字数", self.search_content_extract_max_chars_spin)
        search_form.addRow("抽取前 N 个候选", self.search_content_extract_top_n_spin)
        search_form.addRow("Bangumi", self.search_bangumi_enabled_check)
        search_form.addRow("Bangumi Base URL", self.search_bangumi_base_url_edit)
        search_form.addRow("Bangumi User-Agent", self.search_bangumi_user_agent_edit)
        search_form.addRow("Bangumi 超时", self.search_bangumi_timeout_spin)
        search_form.addRow("Bangumi 最大 query", self.search_bangumi_max_queries_spin)
        search_form.addRow("萌娘百科", self.search_moegirl_enabled_check)
        search_form.addRow("萌娘 API URL", self.search_moegirl_api_url_edit)
        search_form.addRow("萌娘 User-Agent", self.search_moegirl_user_agent_edit)
        search_form.addRow("萌娘 parse API", self.search_moegirl_parse_check)
        search_form.addRow("萌娘 wikitext fallback", self.search_moegirl_wikitext_check)
        search_form.addRow("萌娘 HTML fallback", self.search_moegirl_html_check)
        search_form.addRow("萌娘最大详情页", self.search_moegirl_max_detail_spin)
        search_form.addRow("萌娘超时", self.search_moegirl_timeout_spin)
        search_form.addRow("Google Books", self.search_google_enabled_check)
        search_form.addRow("Google API Key 环境变量", self.search_google_key_env_edit)
        search_form.addRow("Google API Key（本地保存）", self.search_google_key_edit)
        search_form.addRow("Google Key 状态", self.search_google_key_status_label)
        search_form.addRow("Google 超时", self.search_google_timeout_spin)
        search_form.addRow("Google 429 cooldown 分钟", self.search_google_cooldown_spin)
        search_form.addRow("NDL Search", self.search_ndl_enabled_check)
        search_form.addRow("NDL Base URL", self.search_ndl_base_url_edit)
        search_form.addRow("NDL 超时", self.search_ndl_timeout_spin)
        search_form.addRow("Open Library", self.search_open_library_enabled_check)
        search_form.addRow("Open Library Base URL", self.search_open_library_base_url_edit)
        search_form.addRow("Open Library 超时", self.search_open_library_timeout_spin)
        search_form.addRow("通用搜索 API", self.search_generic_provider_combo)
        search_form.addRow("通用搜索 endpoint", self.search_generic_endpoint_edit)
        search_form.addRow("通用搜索 Key 环境变量", self.search_generic_key_env_edit)
        search_form.addRow("通用搜索 API Key（本地保存）", self.search_generic_key_edit)
        search_form.addRow("通用搜索 Key 状态", self.search_generic_key_status_label)
        search_form.addRow("Amazon JP", self.search_amazon_jp_enabled_check)
        search_save_btn = QPushButton("保存搜索设置")
        search_save_btn.clicked.connect(self._save_search_settings)
        search_btns = QHBoxLayout()
        search_btns.addWidget(search_save_btn)
        search_btns.addWidget(self.search_test_button)
        search_btns.addStretch()
        search_form.addRow("", search_btns)
        search_group.setLayout(search_form)

        cache_group = QGroupBox("缓存与日志")
        cache_layout = QVBoxLayout()
        cache_buttons_1 = QHBoxLayout()
        clear_book_ai_btn = QPushButton("清理当前书 AI 建议缓存")
        clear_book_ai_btn.clicked.connect(self._clear_current_book_ai_cache)
        clear_all_ai_btn = QPushButton("清理全部 AI 建议缓存")
        clear_all_ai_btn.clicked.connect(self._clear_all_ai_cache)
        clear_book_search_btn = QPushButton("清理当前书搜索缓存")
        clear_book_search_btn.clicked.connect(self._clear_current_book_search_cache)
        clear_all_search_btn = QPushButton("清理全部搜索缓存")
        clear_all_search_btn.clicked.connect(self._clear_all_search_cache)
        cache_buttons_1.addWidget(clear_book_ai_btn)
        cache_buttons_1.addWidget(clear_all_ai_btn)
        cache_buttons_1.addWidget(clear_book_search_btn)
        cache_buttons_1.addWidget(clear_all_search_btn)
        cache_buttons_2 = QHBoxLayout()
        view_book_logs_btn = QPushButton("查看当前书 AI 请求日志")
        view_book_logs_btn.clicked.connect(self._show_current_book_ai_logs)
        view_all_logs_btn = QPushButton("查看全部 AI 请求日志")
        view_all_logs_btn.clicked.connect(self._show_all_ai_logs)
        clear_logs_btn = QPushButton("清理 AI 请求日志")
        clear_logs_btn.clicked.connect(self._clear_all_ai_request_logs)
        clear_cover_cache_btn = QPushButton("清理未引用封面缓存")
        clear_cover_cache_btn.clicked.connect(self._clear_unreferenced_cover_cache)
        clear_old_logs_btn = QPushButton("清理旧日志文件")
        clear_old_logs_btn.clicked.connect(self._clear_old_logs)
        cache_buttons_2.addWidget(view_book_logs_btn)
        cache_buttons_2.addWidget(view_all_logs_btn)
        cache_buttons_2.addWidget(clear_logs_btn)
        cache_buttons_3 = QHBoxLayout()
        cache_buttons_3.addWidget(clear_cover_cache_btn)
        cache_buttons_3.addWidget(clear_old_logs_btn)
        cache_buttons_3.addStretch()
        cache_layout.addLayout(cache_buttons_1)
        cache_layout.addLayout(cache_buttons_2)
        cache_layout.addLayout(cache_buttons_3)
        cache_group.setLayout(cache_layout)

        # Help & Logs section
        help_group = QGroupBox("帮助与日志")
        help_layout = QHBoxLayout()
        open_log_btn = QPushButton("打开日志文件")
        open_log_btn.clicked.connect(self._open_log_file)
        open_log_dir_btn = QPushButton("打开日志目录")
        open_log_dir_btn.clicked.connect(self._open_log_dir)
        open_data_btn = QPushButton("打开数据目录")
        open_data_btn.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(Path("data").resolve()))))
        open_readme_btn = QPushButton("打开 README")
        open_readme_btn.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(Path("README.md").resolve()))))
        copy_diag_btn = QPushButton("复制诊断信息")
        copy_diag_btn.clicked.connect(self._copy_diagnostic_info)
        help_layout.addWidget(open_log_btn)
        help_layout.addWidget(open_log_dir_btn)
        help_layout.addWidget(open_data_btn)
        help_layout.addWidget(open_readme_btn)
        help_layout.addWidget(copy_diag_btn)
        help_layout.addStretch()
        help_group.setLayout(help_layout)

        scroll_content = QVBoxLayout()
        scroll_content.setSpacing(12)
        scroll_content.addWidget(output_group)
        scroll_content.addWidget(ai_group)
        scroll_content.addWidget(search_group)
        scroll_content.addWidget(cache_group)
        scroll_content.addWidget(help_group)
        scroll_content.addStretch()

        scroll_widget = QWidget()
        scroll_widget.setLayout(scroll_content)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(scroll_widget)

        outer = QVBoxLayout()
        outer.addWidget(scroll)

        container = QWidget()
        container.setLayout(outer)
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
        if hasattr(self, "export_output_label"):
            self.export_output_label.setText(text)

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

    def _load_search_settings_into_widgets(self) -> None:
        config = load_search_config(_GuiAiRepository())
        provider_index = self.search_provider_combo.findData(config.provider_type)
        self.search_provider_combo.setCurrentIndex(provider_index if provider_index >= 0 else 0)
        self.search_enabled_check.setChecked(config.enabled)
        self.search_timeout_spin.setValue(config.timeout_seconds)
        self.search_max_candidates_spin.setValue(config.max_candidates)
        self.search_max_detail_pages_spin.setValue(config.max_detail_pages)
        self.search_ai_query_planner_check.setChecked(config.ai_query_planner_enabled)
        self.search_ai_content_extraction_check.setChecked(config.ai_content_extraction_enabled)
        self.search_content_extract_max_chars_spin.setValue(config.content_extract_max_chars)
        self.search_content_extract_top_n_spin.setValue(config.content_extract_top_n)
        self.search_bangumi_enabled_check.setChecked(config.bangumi_enabled)
        self.search_bangumi_base_url_edit.setText(config.bangumi_base_url)
        self.search_bangumi_user_agent_edit.setText(config.bangumi_user_agent)
        self.search_bangumi_timeout_spin.setValue(config.bangumi_timeout_seconds)
        self.search_bangumi_max_queries_spin.setValue(config.bangumi_max_queries)
        self.search_moegirl_enabled_check.setChecked(config.moegirl_enabled)
        self.search_moegirl_api_url_edit.setText(config.moegirl_api_url)
        self.search_moegirl_user_agent_edit.setText(config.moegirl_user_agent)
        self.search_moegirl_parse_check.setChecked(config.moegirl_parse_api_enabled)
        self.search_moegirl_wikitext_check.setChecked(config.moegirl_wikitext_fallback_enabled)
        self.search_moegirl_html_check.setChecked(config.moegirl_html_fallback_enabled)
        self.search_moegirl_max_detail_spin.setValue(config.moegirl_max_detail_pages)
        self.search_moegirl_timeout_spin.setValue(config.moegirl_timeout_seconds)
        self.search_google_enabled_check.setChecked(config.google_books_enabled)
        self.search_google_key_env_edit.setText(config.google_books_api_key_env)
        self.search_google_timeout_spin.setValue(config.google_books_timeout_seconds)
        self.search_google_cooldown_spin.setValue(config.google_books_cooldown_minutes)
        self.search_ndl_enabled_check.setChecked(config.ndl_enabled)
        self.search_ndl_base_url_edit.setText(config.ndl_base_url)
        self.search_ndl_timeout_spin.setValue(config.ndl_timeout_seconds)
        self.search_open_library_enabled_check.setChecked(config.open_library_enabled)
        self.search_open_library_base_url_edit.setText(config.open_library_base_url)
        self.search_open_library_timeout_spin.setValue(config.open_library_timeout_seconds)
        generic_index = self.search_generic_provider_combo.findData(config.generic_search_provider)
        self.search_generic_provider_combo.setCurrentIndex(generic_index if generic_index >= 0 else 0)
        self.search_generic_endpoint_edit.setText(config.generic_search_endpoint)
        self.search_generic_key_env_edit.setText(config.generic_search_api_key_env)
        self.search_amazon_jp_enabled_check.setChecked(config.amazon_jp_enabled)
        self._refresh_search_key_status(config)

    def _search_config_from_settings_form(self) -> SearchConfig:
        return SearchConfig(
            provider_type=str(self.search_provider_combo.currentData() or "duckduckgo"),
            enabled=self.search_enabled_check.isChecked(),
            timeout_seconds=int(self.search_timeout_spin.value()),
            max_candidates=int(self.search_max_candidates_spin.value()),
            max_detail_pages=int(self.search_max_detail_pages_spin.value()),
            ai_query_planner_enabled=self.search_ai_query_planner_check.isChecked(),
            ai_content_extraction_enabled=self.search_ai_content_extraction_check.isChecked(),
            content_extract_max_chars=int(self.search_content_extract_max_chars_spin.value()),
            content_extract_top_n=int(self.search_content_extract_top_n_spin.value()),
            bangumi_enabled=self.search_bangumi_enabled_check.isChecked(),
            bangumi_base_url=self.search_bangumi_base_url_edit.text().strip() or "https://api.bgm.tv",
            bangumi_user_agent=self.search_bangumi_user_agent_edit.text().strip() or "LightBookStudio/0.4",
            bangumi_timeout_seconds=int(self.search_bangumi_timeout_spin.value()),
            bangumi_max_queries=int(self.search_bangumi_max_queries_spin.value()),
            moegirl_enabled=self.search_moegirl_enabled_check.isChecked(),
            moegirl_api_url=self.search_moegirl_api_url_edit.text().strip() or "https://zh.moegirl.org.cn/api.php",
            moegirl_user_agent=self.search_moegirl_user_agent_edit.text().strip() or "LightBookStudio/0.4",
            moegirl_parse_api_enabled=self.search_moegirl_parse_check.isChecked(),
            moegirl_wikitext_fallback_enabled=self.search_moegirl_wikitext_check.isChecked(),
            moegirl_html_fallback_enabled=self.search_moegirl_html_check.isChecked(),
            moegirl_max_detail_pages=int(self.search_moegirl_max_detail_spin.value()),
            moegirl_timeout_seconds=int(self.search_moegirl_timeout_spin.value()),
            google_books_enabled=self.search_google_enabled_check.isChecked(),
            google_books_api_key_env=self.search_google_key_env_edit.text().strip() or "GOOGLE_BOOKS_API_KEY",
            google_books_timeout_seconds=int(self.search_google_timeout_spin.value()),
            google_books_cooldown_minutes=int(self.search_google_cooldown_spin.value()),
            ndl_enabled=self.search_ndl_enabled_check.isChecked(),
            ndl_base_url=self.search_ndl_base_url_edit.text().strip(),
            ndl_timeout_seconds=int(self.search_ndl_timeout_spin.value()),
            open_library_enabled=self.search_open_library_enabled_check.isChecked(),
            open_library_base_url=self.search_open_library_base_url_edit.text().strip() or "https://openlibrary.org",
            open_library_timeout_seconds=int(self.search_open_library_timeout_spin.value()),
            generic_search_provider=str(self.search_generic_provider_combo.currentData() or "disabled"),
            generic_search_endpoint=self.search_generic_endpoint_edit.text().strip(),
            generic_search_api_key_env=self.search_generic_key_env_edit.text().strip() or "LIGHTBOOK_SEARCH_API_KEY",
            amazon_jp_enabled=self.search_amazon_jp_enabled_check.isChecked(),
        )

    def _save_search_settings(self) -> None:
        config = self._search_config_from_settings_form()
        try:
            if self.search_google_key_edit.text().strip():
                set_secret("google_books_api_key", self.search_google_key_edit.text().strip())
                self.search_google_key_edit.clear()
            if self.search_generic_key_edit.text().strip():
                set_secret("generic_search_api_key", self.search_generic_key_edit.text().strip())
                self.search_generic_key_edit.clear()
            save_search_config(_GuiAiRepository(), config)
        except Exception as exc:
            logger.exception("Failed to save search settings")
            self._show_error(f"保存搜索设置失败：{exc}")
            return
        self._refresh_search_key_status(config)
        QMessageBox.information(self, "搜索设置", "搜索设置已保存。")

    def _refresh_search_key_status(self, config: SearchConfig) -> None:
        google_loaded = bool(os.environ.get(config.google_books_api_key_env) or has_secret("google_books_api_key"))
        generic_loaded = bool(os.environ.get(config.generic_search_api_key_env) or has_secret("generic_search_api_key"))
        self.search_google_key_status_label.setText(f"已配置：{google_loaded}")
        self.search_generic_key_status_label.setText(f"已配置：{generic_loaded}")

    def _test_search_settings(self) -> None:
        config = self._search_config_from_settings_form()
        self._refresh_search_key_status(config)
        enabled = []
        if config.bangumi_enabled:
            enabled.append("Bangumi")
        if config.moegirl_enabled:
            enabled.append("萌娘百科")
        if config.google_books_enabled:
            enabled.append("Google Books")
        if config.ndl_enabled:
            enabled.append("NDL")
        if config.open_library_enabled:
            enabled.append("Open Library")
        QMessageBox.information(
            self,
            "搜索配置",
            "配置可用。启用来源："
            + (", ".join(enabled) if enabled else "无")
            + "\nAPI Key 不会写入 app_settings；本地输入保存到 data/local_secrets.json。",
        )

    def _save_splitter_sizes(self, *args: object) -> None:
        try:
            if hasattr(self, "main_splitter"):
                set_setting("ui_main_splitter_sizes", json.dumps(self.main_splitter.sizes()))
            if hasattr(self, "chapter_splitter"):
                set_setting("ui_chapter_splitter_sizes", json.dumps(self.chapter_splitter.sizes()))
            if hasattr(self, "cover_search_splitter"):
                set_setting("ui_cover_search_splitter_sizes", json.dumps(self.cover_search_splitter.sizes()))
            if hasattr(self, "detail_tabs"):
                set_setting("ui_detail_current_tab", str(self.detail_tabs.currentIndex()))
        except Exception:
            logger.exception("Failed to save splitter sizes")

    def _clear_current_book_ai_cache(self) -> None:
        book_id = self.current_book_id
        if book_id is None:
            self._show_error("请先选择一个 book。")
            return
        if QMessageBox.question(self, "清理 AI 缓存", "清理当前书 AI 建议缓存？") != QMessageBox.StandardButton.Yes:
            return
        count = delete_ai_suggestions_by_book(book_id)
        self._clear_ai_suggestion_table()
        QMessageBox.information(self, "清理 AI 缓存", f"已清理 {count} 条。")

    def _clear_all_ai_cache(self) -> None:
        if QMessageBox.question(self, "清理 AI 缓存", "清理全部 AI 建议缓存？") != QMessageBox.StandardButton.Yes:
            return
        count = delete_all_ai_suggestions()
        self._clear_ai_suggestion_table()
        QMessageBox.information(self, "清理 AI 缓存", f"已清理 {count} 条。")

    def _clear_all_search_cache(self) -> None:
        if QMessageBox.question(self, "清理搜索缓存", "清理全部搜索结果缓存？") != QMessageBox.StandardButton.Yes:
            return
        count = delete_all_metadata_search_results()
        self.search_status_label.setText("尚未搜索封面/资料。")
        if hasattr(self, "search_diag_label"):
            self.search_diag_label.setText("")
        QMessageBox.information(self, "清理搜索缓存", f"已清理 {count} 条。")

    def _show_current_book_ai_logs(self) -> None:
        book_id = self.current_book_id
        if book_id is None:
            self._show_error("请先选择一个 book。")
            return
        self._show_ai_logs(list_ai_request_logs_by_book(book_id), title=f"当前书 AI 请求日志：{book_id}")

    def _show_all_ai_logs(self) -> None:
        self._show_ai_logs(list_ai_request_logs(), title="全部 AI 请求日志")

    def _show_ai_logs(self, rows: list[RowDict], *, title: str) -> None:
        if not rows:
            QMessageBox.information(self, title, "没有 AI 请求日志。")
            return
        blocks: list[str] = []
        for row in rows[:20]:
            blocks.append(
                "\n".join(
                    [
                        f"时间: {row.get('created_at')}",
                        f"类型: {row.get('request_type')}",
                        f"Provider/Model: {row.get('provider')} / {row.get('model')}",
                        f"状态: {row.get('status')}  耗时: {row.get('duration_ms')}ms",
                        f"请求: {str(row.get('request_json') or '')[:800]}",
                        f"响应: {str(row.get('response_text') or '')[:1200]}",
                        f"错误: {row.get('error_message') or ''}",
                    ]
                )
            )
        QMessageBox.information(self, title, "\n\n---\n\n".join(blocks))

    def _clear_all_ai_request_logs(self) -> None:
        if QMessageBox.question(self, "清理 AI 请求日志", "清理全部 AI 请求日志？") != QMessageBox.StandardButton.Yes:
            return
        count = delete_all_ai_request_logs()
        QMessageBox.information(self, "清理 AI 请求日志", f"已清理 {count} 条。")

    def _clear_unreferenced_cover_cache(self) -> None:
        covers_root = Path("data") / "covers"
        referenced_paths = {
            Path(str(book.get("cover_override_path", "")))
            for book in list_books()
            if str(book.get("cover_override_path", "")).strip()
        }
        normalized_refs = {path.resolve(strict=False) for path in referenced_paths}
        candidates = [
            path
            for path in covers_root.rglob("*")
            if path.is_file() and path.resolve(strict=False) not in normalized_refs
        ] if covers_root.exists() else []
        if not candidates:
            QMessageBox.information(self, "清理封面缓存", "没有未引用的封面缓存。")
            return
        if QMessageBox.question(
            self,
            "清理封面缓存",
            f"将删除 data/covers 下 {len(candidates)} 个未引用封面缓存文件，不会删除原始导入文件。继续？",
        ) != QMessageBox.StandardButton.Yes:
            return
        count = cleanup_unreferenced_cover_cache(covers_root, referenced_paths)
        QMessageBox.information(self, "清理封面缓存", f"已清理 {count} 个文件。")

    def _clear_old_logs(self) -> None:
        candidates = [path for path in LOG_DIR.glob("lightbook.log.*") if path.is_file()] if LOG_DIR.exists() else []
        if not candidates:
            QMessageBox.information(self, "清理旧日志", "没有旧日志文件。")
            return
        if QMessageBox.question(
            self,
            "清理旧日志",
            f"将删除 {len(candidates)} 个轮转旧日志文件，保留当前日志。继续？",
        ) != QMessageBox.StandardButton.Yes:
            return
        count = cleanup_old_log_files(LOG_DIR, LOG_FILE)
        QMessageBox.information(self, "清理旧日志", f"已清理 {count} 个文件。")

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
        import time as _time
        started = _time.perf_counter()
        try:
            provider = create_ai_provider(config)
            if isinstance(provider, OpenAICompatibleProvider):
                provider.test_connection()
            else:
                raise LightBookError("当前 provider 不支持测试连接。")
            create_ai_request_log(
                book_id=self.current_book_id,
                task_id="test_connection",
                request_type="test_connection",
                provider=config.provider_type,
                model=config.model,
                request_json={"base_url": config.base_url, "model": config.model},
                response_text='{"ok": true}',
                parsed_json={"ok": True},
                status="completed",
                duration_ms=int((_time.perf_counter() - started) * 1000),
            )
        except AiProviderConfigError:
            self._show_error(f"未配置 API Key，请设置环境变量 {config.api_key_env}。")
            return
        except Exception as exc:
            create_ai_request_log(
                book_id=self.current_book_id,
                task_id="test_connection",
                request_type="test_connection",
                provider=config.provider_type,
                model=config.model,
                request_json={"base_url": config.base_url, "model": config.model},
                status="failed",
                error_message=str(exc),
                duration_ms=int((_time.perf_counter() - started) * 1000),
            )
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
                if column_index in (2, 5):
                    item.setToolTip(value)
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
            self.current_book_id = None
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
        ai_action = menu.addAction("为选中项生成 AI 建议")
        ai_apply_action = menu.addAction("生成并应用 AI 建议")
        search_action = menu.addAction("为选中项搜索封面/资料")
        search_apply_action = menu.addAction("搜索并应用资料")
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
        elif selected_action == ai_action:
            self._batch_generate_ai_suggestions(apply=False)
        elif selected_action == ai_apply_action:
            self._batch_generate_ai_suggestions(apply=True)
        elif selected_action == search_action:
            self._batch_search_metadata(apply=False)
        elif selected_action == search_apply_action:
            self._batch_search_metadata(apply=True)
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

    def _batch_generate_ai_suggestions(self, *, apply: bool) -> None:
        book_ids = self._selected_batch_book_ids()
        if not book_ids:
            self._show_error("请先选择一个或多个 book。")
            return

        import app.gui.workers as w

        def work() -> object:
            config = load_ai_provider_config(_GuiAiRepository())
            provider = create_ai_provider(config)
            service = AiSuggestionService(_GuiAiRepository(), provider)
            summary = {"total": len(book_ids), "success": 0, "failed": 0, "applied": 0, "errors": []}
            for index, book_id in enumerate(book_ids, start=1):
                logger.info("Batch AI suggestion %s/%s book_id=%s apply=%s", index, len(book_ids), book_id, apply)
                try:
                    service.generate_for_book(book_id)
                    summary["success"] += 1
                    if apply:
                        latest = list_latest_ai_suggestion_by_book(book_id)
                        if latest:
                            applied = _apply_safe_ai_suggestion(book_id, latest, _GuiAiRepository())
                            summary["applied"] += applied
                except Exception as exc:
                    summary["failed"] += 1
                    summary["errors"].append(f"book {book_id}: {exc}")
                    logger.warning("Batch AI suggestion failed book_id=%s: %s", book_id, exc)
            return summary

        def on_result(_tid: str, _tname: str, _bid: object, result: object) -> None:
            if isinstance(result, dict):
                self._refresh_batch_table(selected_book_id=self.current_book_id)
                if self.current_book_id is not None:
                    self._load_ai_suggestion_cache_for_book(self.current_book_id)
                errors = result.get("errors") or []
                message = (
                    f"处理完成：成功 {result.get('success', 0)}，失败 {result.get('failed', 0)}，"
                    f"应用字段 {result.get('applied', 0)}。"
                )
                if errors:
                    message += "\n\n失败详情：\n" + "\n".join(str(e) for e in errors[:10])
                QMessageBox.information(self, "批量 AI 建议", message)

        handle = w.submit_background_task(
            task_name="batch_ai_suggestion",
            book_id=None,
            fn=work,
            on_result=on_result,
            on_error=lambda _tid, _tname, _bid, err: self._show_error(f"批量 AI 建议失败：{err[:400]}"),
            on_finished=lambda _tid, _tname, _bid: self._active_handles.pop(_tid, None),
        )
        self._active_handles[handle.task_id] = handle

    def _batch_search_metadata(self, *, apply: bool) -> None:
        book_ids = self._selected_batch_book_ids()
        if not book_ids:
            self._show_error("请先选择一个或多个 book。")
            return
        search_config = load_search_config(_GuiAiRepository())
        if not search_config.enabled:
            self._show_error("联网搜索未启用，请在设置中开启。")
            return
        apply_cover = False
        if apply:
            apply_cover = (
                QMessageBox.question(
                    self,
                    "批量应用资料",
                    "是否同时下载并应用候选封面？\n选择“否”时只应用简介、分类、标签和空作者。",
                )
                == QMessageBox.StandardButton.Yes
            )

        import app.gui.workers as w

        def work() -> object:
            from app.search.search_pipeline import search_metadata_candidates
            summary = {"total": len(book_ids), "success": 0, "failed": 0, "applied": 0, "errors": []}
            content_extractor = self._build_content_extractor() if search_config.ai_content_extraction_enabled else None
            for index, book_id in enumerate(book_ids, start=1):
                logger.info("Batch metadata search %s/%s book_id=%s apply=%s", index, len(book_ids), book_id, apply)
                try:
                    search_query = _search_query_for_book(book_id)
                    result = search_metadata_candidates(
                        search_query,
                        max_candidates=search_config.max_candidates,
                        content_extractor=content_extractor,
                        book_id=book_id,
                        search_config=search_config,
                    )
                    create_metadata_search_result(
                        book_id=book_id,
                        provider=search_config.provider_type,
                        query_snapshot=asdict(search_query),
                        diagnostics_json={"providers": [asdict(diag) for diag in result.diagnostics]},
                        candidates_json=[_metadata_candidate_to_dict(candidate) for candidate in result.candidates],
                        status="completed",
                    )
                    summary["success"] += 1
                    if apply:
                        candidate = _best_extracted_candidate(result.candidates)
                        if candidate is not None:
                            fields = _safe_search_apply_fields(book_id, candidate, include_cover=apply_cover)
                            if fields:
                                candidate = _candidate_with_merged_terms(book_id, candidate)
                                MetadataSearchService(
                                    _GuiAiRepository(),
                                    create_metadata_search_provider(search_config, _GuiAiRepository()),
                                ).apply_candidate(book_id, candidate, fields)
                                summary["applied"] += len(fields)
                except Exception as exc:
                    create_metadata_search_result(
                        book_id=book_id,
                        provider=search_config.provider_type,
                        query_snapshot={},
                        diagnostics_json={},
                        candidates_json=[],
                        status="failed",
                        error_message=str(exc),
                    )
                    summary["failed"] += 1
                    summary["errors"].append(f"book {book_id}: {exc}")
                    logger.warning("Batch metadata search failed book_id=%s: %s", book_id, exc)
            return summary

        def on_result(_tid: str, _tname: str, _bid: object, result: object) -> None:
            if isinstance(result, dict):
                self._refresh_batch_table(selected_book_id=self.current_book_id)
                if self.current_book_id is not None:
                    self._load_search_cache_for_book(self.current_book_id)
                errors = result.get("errors") or []
                message = (
                    f"搜索完成：成功 {result.get('success', 0)}，失败 {result.get('failed', 0)}，"
                    f"应用字段 {result.get('applied', 0)}。"
                )
                if errors:
                    message += "\n\n失败详情：\n" + "\n".join(str(e) for e in errors[:10])
                QMessageBox.information(self, "批量搜索资料", message)

        handle = w.submit_background_task(
            task_name="batch_metadata_search",
            book_id=None,
            fn=work,
            on_result=on_result,
            on_error=lambda _tid, _tname, _bid, err: self._show_error(f"批量搜索资料失败：{err[:400]}"),
            on_finished=lambda _tid, _tname, _bid: self._active_handles.pop(_tid, None),
        )
        self._active_handles[handle.task_id] = handle

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

        preview_titles: list[str] = []
        for book in books[:10]:
            work = get_work(int(book["work_id"])) or {}
            title = str(work.get("title") or book.get("title") or book.get("source_path") or "")
            preview_titles.append(title)
        extra_count = len(books) - len(preview_titles)
        path_text = "\n".join(preview_titles)
        if extra_count > 0:
            path_text += f"\n... 以及另外 {extra_count} 项"
        answer = QMessageBox.question(
            self,
            "删除",
            f"从批量整理列表和数据库中删除选中的 {len(books)} 项？\n"
            f"{path_text}\n\n"
            "只会删除数据库记录和关联章节、导出任务、AI 建议、搜索缓存、AI 请求日志，不会删除原始文件。",
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
        self.current_book_id = book_id
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
        self._load_ai_suggestion_cache_for_book(book_id)
        self._load_search_cache_for_book(book_id)
        self._refresh_task_button_states(book_id)

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

        task_type = "ai_suggestion"
        task_key = f"{task_type}:{book_id}"
        task_tuple = (task_type, book_id)
        if task_tuple in self._running_book_tasks:
            self.ai_status_label.setText("该条目正在生成 AI 建议…")
            return

        import app.gui.workers as w

        logger.info("Generate AI suggestion clicked book_id=%s", book_id)

        self._running_tasks.add(task_key)
        self._running_book_tasks.add(task_tuple)
        self._refresh_task_button_states(book_id)
        self.ai_status_label.setText("正在生成 AI 建议…")

        def work() -> object:
            config = load_ai_provider_config(_GuiAiRepository())
            provider = create_ai_provider(config)
            service = AiSuggestionService(_GuiAiRepository(), provider)
            service.generate_for_book(book_id)
            latest = list_latest_ai_suggestion_by_book(book_id)
            if latest is None:
                raise LightBookError("AI 建议已生成，但无法从数据库读取。")
            return latest

        def on_result(_tid: str, _tname: str, _bid: object, result: object) -> None:
            if not isinstance(result, dict):
                return
            self._display_ai_suggestion(result, expected_book_id=int(_bid))
            if _bid == self.current_book_id and self.ai_suggestion_table.rowCount() > 0:
                self.ai_status_label.setText("AI 建议已生成。请选择需要应用的字段。")

        def on_error(_tid: str, _tname: str, _bid: object, err: str) -> None:
            if _bid != self.current_book_id:
                logger.info("AI task failed for non-current book_id=%s current=%s", _bid, self.current_book_id)
                return
            if "API Key" in err or "api_key" in err.lower():
                config = load_ai_provider_config(_GuiAiRepository())
                self._show_error(f"未配置 API Key，请设置环境变量 {config.api_key_env}。")
            else:
                self.ai_status_label.setText(f"AI 建议生成失败：{err[:200]}")
                self._show_error(f"AI 建议生成失败：{err[:200]}")

        def on_finished(_tid: str, _tname: str, _bid: object) -> None:
            self._running_tasks.discard(task_key)
            self._running_book_tasks.discard(task_tuple)
            self._active_handles.pop(_tid, None)
            if _bid == self.current_book_id:
                self._refresh_task_button_states(int(_bid))

        handle = w.submit_background_task(
            task_name="ai_suggestion", book_id=book_id, fn=work,
            on_result=on_result, on_error=on_error, on_finished=on_finished,
        )
        self._active_handles[handle.task_id] = handle

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
        if self.current_ai_suggestion_row is not None:
            self._populate_ai_suggestion_table(self.current_ai_suggestion_row)
        QMessageBox.information(self, "AI 辅助", "已应用选中字段。")

    def _ignore_ai_suggestion(self) -> None:
        self._clear_ai_suggestion_table()

    def _load_ai_suggestion_cache_for_book(self, book_id: int) -> None:
        cached = list_latest_ai_suggestion_by_book(book_id)
        if cached is None:
            self._clear_ai_suggestion_table()
            return
        self._display_ai_suggestion(cached, expected_book_id=book_id)

    def _load_cached_ai_suggestion(self, book_id: int) -> None:
        self._load_ai_suggestion_cache_for_book(book_id)

    def _display_ai_suggestion(self, suggestion: RowDict, expected_book_id: int) -> None:
        if not should_refresh_book_cache(
            expected_book_id=expected_book_id,
            current_book_id=self.current_book_id,
            cached_row=suggestion,
        ):
            logger.info(
                "Skip AI suggestion UI refresh expected_book_id=%s current_book_id=%s",
                expected_book_id,
                self.current_book_id,
            )
            return
        status = str(suggestion.get("status", ""))
        if status == "completed":
            self.current_ai_suggestion_id = int(suggestion["id"])
            self._populate_ai_suggestion_table(suggestion)
            if self.ai_suggestion_table.rowCount() > 0:
                self.ai_status_label.setText("已加载缓存的 AI 建议。")
            return
        if status == "failed":
            self._clear_ai_suggestion_table()
            err = str(suggestion.get("error_message", "")) or "未知错误"
            self.ai_status_label.setText(f"上次 AI 建议失败：{err[:100]}")
            return
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

    def _set_ai_apply_checks(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for row in range(self.ai_suggestion_table.rowCount()):
            item = self.ai_suggestion_table.item(row, 3)
            if item is None:
                continue
            if item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                item.setCheckState(state)

    def _select_empty_ai_fields(self) -> None:
        for row in range(self.ai_suggestion_table.rowCount()):
            current_item = self.ai_suggestion_table.item(row, 1)
            apply_item = self.ai_suggestion_table.item(row, 3)
            if apply_item is None:
                continue
            if not (apply_item.flags() & Qt.ItemFlag.ItemIsUserCheckable):
                continue
            current_value = current_item.text().strip() if current_item else ""
            apply_item.setCheckState(
                Qt.CheckState.Checked if not current_value else Qt.CheckState.Unchecked
            )

    def _select_title_summary_genre_ai_fields(self) -> None:
        title_summary_genre_fields = {"clean_title", "book_title", "summary", "genres", "tags"}
        for row in range(self.ai_suggestion_table.rowCount()):
            apply_item = self.ai_suggestion_table.item(row, 3)
            if apply_item is None:
                continue
            if not (apply_item.flags() & Qt.ItemFlag.ItemIsUserCheckable):
                continue
            field_name = str(apply_item.data(Qt.ItemDataRole.UserRole) or "")
            apply_item.setCheckState(
                Qt.CheckState.Checked if field_name in title_summary_genre_fields else Qt.CheckState.Unchecked
            )

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
        self._do_search_cover(book_id)

    def _build_content_extractor(self) -> object | None:
        try:
            ai_config = load_ai_provider_config(_GuiAiRepository())
            provider_type = ai_config.provider_type.strip().lower()
            api_key = get_api_key_from_env(ai_config)
            if provider_type == "openai_compatible" and not api_key:
                logger.info(
                    "AI content extraction skipped: API key env %s is not configured",
                    ai_config.api_key_env,
                )
                return None
            ai_provider = create_ai_provider(ai_config)
            if not hasattr(ai_provider, "extract_from_content"):
                logger.info("AI provider %s does not support content extraction", ai_provider.__class__.__name__)
                return None
            from app.search.content_extractor import MetadataContentExtractor
            search_config = load_search_config(_GuiAiRepository())
            return MetadataContentExtractor(
                ai_provider,
                _GuiAiRepository(),
                max_content_length=search_config.content_extract_max_chars,
            )
        except Exception as exc:
            logger.debug("AI content extractor not available, skipping extraction: %s", exc)
            return None

    def _load_search_cache_for_book(self, book_id: int) -> None:
        cached = get_latest_metadata_search_result_by_book(book_id)
        if cached is None:
            self.search_status_label.setText("尚未搜索封面/资料。")
            if hasattr(self, "search_diag_label"):
                self.search_diag_label.setText("")
            return
        self._display_search_result(cached, expected_book_id=book_id, open_dialog=False)

    def _display_search_result(
        self,
        result: RowDict,
        expected_book_id: int,
        *,
        open_dialog: bool = False,
    ) -> None:
        if not should_refresh_book_cache(
            expected_book_id=expected_book_id,
            current_book_id=self.current_book_id,
            cached_row=result,
        ):
            logger.info(
                "Skip search cache UI refresh expected_book_id=%s current_book_id=%s",
                expected_book_id,
                self.current_book_id,
            )
            return
        candidates = _metadata_candidates_from_json(result.get("candidates_json"))
        status = str(result.get("status") or "")
        created_at = str(result.get("created_at") or "")
        if status == "failed":
            err = str(result.get("error_message") or "未知错误")
            self.search_status_label.setText(f"上次搜索失败：{err[:120]}")
            if hasattr(self, "search_diag_label"):
                self.search_diag_label.setText("")
            return
        self.search_status_label.setText(f"上次搜索：{created_at}，候选 {len(candidates)} 个。")
        diag = _json_dict(result.get("diagnostics_json"))
        provider_summary = diag.get("providers", [])
        if hasattr(self, "search_diag_label") and provider_summary:
            lines = []
            for p in provider_summary:
                if not isinstance(p, dict):
                    continue
                name = p.get("name", "")
                enabled = p.get("enabled", False)
                cnt = p.get("candidate_count", 0)
                err = p.get("error", "")
                if not enabled:
                    lines.append(f"{name}: 已跳过")
                elif err:
                    lines.append(f"{name}: 错误 - {err}")
                else:
                    lines.append(f"{name}: {cnt} 个候选")
            self.search_diag_label.setText("  |  ".join(lines))
        if open_dialog:
            self._open_search_candidates_dialog(expected_book_id, candidates)

    def _show_cached_search_result(self) -> None:
        book_id = self.current_book_id
        if book_id is None:
            self._show_error("请先选择一个 book。")
            return
        cached = get_latest_metadata_search_result_by_book(book_id)
        if cached is None:
            QMessageBox.information(self, "搜索封面/资料", "当前书没有搜索缓存。")
            return
        self._display_search_result(cached, expected_book_id=book_id, open_dialog=True)

    def _clear_current_book_search_cache(self) -> None:
        book_id = self.current_book_id
        if book_id is None:
            self._show_error("请先选择一个 book。")
            return
        answer = QMessageBox.question(self, "清除搜索缓存", "清除当前书的搜索结果缓存？")
        if answer != QMessageBox.StandardButton.Yes:
            return
        count = delete_metadata_search_results_by_book(book_id)
        self.search_status_label.setText("尚未搜索封面/资料。")
        if hasattr(self, "search_diag_label"):
            self.search_diag_label.setText("")
        QMessageBox.information(self, "清除搜索缓存", f"已清除 {count} 条搜索缓存。")

    def _open_search_candidates_dialog(self, book_id: int, candidates: list[object]) -> None:
        if not candidates:
            QMessageBox.information(self, "搜索封面/资料", "缓存中没有候选结果。")
            return
        dialog = MetadataSearchDialog(candidates, self)  # type: ignore[arg-type]
        dialog.exec()
        candidate = dialog.chosen_candidate()
        if candidate is None:
            return
        fields = dialog.chosen_fields()
        manual_url = dialog.manual_cover_url
        if manual_url:
            self._apply_manual_cover(book_id, manual_url)
        if fields:
            service = MetadataSearchService(
                _GuiAiRepository(),
                create_metadata_search_provider(load_search_config(_GuiAiRepository()), _GuiAiRepository()),
            )
            service.apply_candidate(book_id, candidate, fields)
            QMessageBox.information(self, "搜索封面/资料", f"已应用字段：{', '.join(fields)}")
        if book_id == self.current_book_id:
            self._refresh_batch_table(selected_book_id=book_id)

    def _refresh_task_button_states(self, book_id: int | None = None) -> None:
        current_id = book_id if book_id is not None else self.current_book_id
        if current_id is None:
            self.ai_generate_button.setEnabled(False)
            self.ai_search_button.setEnabled(False)
            return
        self.ai_generate_button.setEnabled(("ai_suggestion", current_id) not in self._running_book_tasks)
        self.ai_search_button.setEnabled(("search_cover", current_id) not in self._running_book_tasks)

    def _set_novel_chapter_widgets_visible(self, visible: bool) -> None:
        if hasattr(self, "chapter_stack"):
            self.chapter_stack.setCurrentIndex(1 if visible else 0)

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
        self.search_status_label.setText("尚未搜索封面/资料。")
        if hasattr(self, "search_diag_label"):
            self.search_diag_label.setText("")
        if hasattr(self, "export_status_label"):
            self.export_status_label.setText("")
        self._refresh_task_button_states(None)
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

    # ── Single import AI methods ──

    def _set_single_ai_enabled(self, enable: bool) -> None:
        self.single_ai_generate_button.setEnabled(enable)
        self.single_ai_apply_button.setEnabled(enable)
        self.single_ai_raw_button.setEnabled(enable)
        self.single_ai_search_button.setEnabled(enable)
        self.single_ai_manual_cover_btn.setEnabled(enable)
        if not enable:
            self.single_ai_status_label.setText("请先保存到库，再使用 AI 建议和封面搜索。")

    def _save_single_to_library(self) -> None:
        if self.import_result is None and self.novel_import_result is None:
            self._show_error("请先选择图片文件夹、EPUB、CBZ 或 TXT。")
            return

        try:
            is_novel = self.novel_import_result is not None
            if is_novel:
                result = self.novel_import_result
                paths = [result.source_path]
            else:
                result = self.import_result
                paths = [result.source_path]

            from app.services.batch_import_service import batch_import
            batch_result = batch_import(paths)
            if batch_result.book_ids:
                self.single_saved_book_id = batch_result.book_ids[-1]
                self._set_single_ai_enabled(True)
                self.single_ai_status_label.setText("AI 已就绪。请点击“生成 AI 建议”获取元数据。")
                QMessageBox.information(self, "保存到库", f"已保存到库（book #{self.single_saved_book_id}），现在可以使用 AI 功能。")
            else:
                self._show_error("保存到库失败。")
        except Exception as exc:
            logger.exception("Failed to save single import to library")
            self._show_error(f"保存到库失败：{exc}")

    def _generate_single_ai_suggestion(self) -> None:
        book_id = self.single_saved_book_id
        if book_id is None:
            self._show_error("请先保存到库。")
            return
        try:
            config = load_ai_provider_config(_GuiAiRepository())
            provider = create_ai_provider(config)
            service = AiSuggestionService(_GuiAiRepository(), provider)
            service.generate_for_book(book_id)
            latest = list_latest_ai_suggestion_by_book(book_id)
            if latest is None:
                raise LightBookError("AI 建议已生成，但无法从数据库读取。")
            self.single_ai_suggestion_id = int(latest["id"])
            self._populate_single_ai_suggestion_table(latest)
            if self.single_ai_suggestion_table.rowCount() > 0:
                self.single_ai_status_label.setText("AI 建议已生成。请选择需要应用的字段。")
        except Exception as exc:
            logger.exception("Failed to generate single AI suggestion")
            self.single_ai_status_label.setText(f"AI 建议生成失败：{exc}")
            self._show_error(f"AI 建议生成失败：{exc}")

    def _apply_single_ai_fields(self) -> None:
        book_id = self.single_saved_book_id
        if book_id is None or self.single_ai_suggestion_id is None:
            self._show_error("请先生成 AI 建议。")
            return
        fields = self._selected_single_ai_fields()
        if not fields:
            QMessageBox.information(self, "AI 辅助", "没有勾选要应用的字段。")
            return
        try:
            service = AiSuggestionService(_GuiAiRepository(), create_ai_provider(load_ai_provider_config(_GuiAiRepository())))
            service.apply_suggestion(book_id, self.single_ai_suggestion_id, fields)
        except Exception as exc:
            logger.exception("Failed to apply single AI suggestion")
            self._show_error(f"应用 AI 建议失败：{exc}")
            return
        self._refresh_single_ai_fields()
        QMessageBox.information(self, "AI 辅助", "已应用选中字段。")

    def _show_single_ai_raw_response(self) -> None:
        suggestion = self.single_ai_suggestion_row
        if suggestion is None and self.single_ai_suggestion_id is not None:
            suggestion = get_ai_suggestion(self.single_ai_suggestion_id)
        if suggestion is None:
            QMessageBox.information(self, "AI 辅助", "当前没有 AI 建议。")
            return
        raw = str(suggestion.get("raw_response") or "")[:3000]
        parsed_text = json.dumps(_json_dict(suggestion.get("parsed_json")), ensure_ascii=False, indent=2)[:3000]
        QMessageBox.information(self, "AI 原始响应", f"Raw response（前 3000 字）：\n{raw}\n\nParsed JSON：\n{parsed_text}")

    def _search_single_cover(self) -> None:
        book_id = self.single_saved_book_id
        if book_id is None:
            self._show_error("请先保存到库。")
            return
        self._do_search_cover(book_id)

    def _single_manual_cover_download(self) -> None:
        book_id = self.single_saved_book_id
        if book_id is None:
            self._show_error("请先保存到库。")
            return
        url = self.single_ai_manual_cover_edit.text().strip()
        if not url:
            return
        if not (url.startswith("http://") or url.startswith("https://")):
            self._show_error("图片链接必须是 http 或 https。")
            return
        try:
            from pathlib import Path as _Path
            from app.search.web_search_service import download_cover as _dl
            target = _Path("data") / "covers" / str(book_id) / "manual_cover.jpg"
            target.parent.mkdir(parents=True, exist_ok=True)
            downloaded = _dl(url, target)
            from app.storage.repositories import update_book_cover_override
            update_book_cover_override(book_id, str(downloaded))
            self.single_cover_override_path = downloaded
            self.single_cover_override_label.setText(str(downloaded))
            self._show_single_import_cover()
            QMessageBox.information(self, "封面下载", f"封面已下载并应用。")
        except Exception as exc:
            logger.exception("Manual cover download failed")
            self._show_error(f"封面下载失败：{exc}")

    def _populate_single_ai_suggestion_table(self, suggestion: RowDict) -> None:
        parsed = _json_dict(suggestion.get("parsed_json"))
        self.single_ai_suggestion_row = suggestion
        self.single_ai_suggestion_table.setRowCount(0)
        row_index = 0
        for field_name, field_label, can_apply in AI_APPLY_FIELDS:
            current_value = self._current_single_ai_field_value(field_name)
            suggested_value = _display_ai_value(parsed.get(field_name))
            if not suggested_value and not current_value:
                continue
            self.single_ai_suggestion_table.insertRow(row_index)
            for col, val in enumerate([field_label, current_value, suggested_value]):
                item = QTableWidgetItem(val)
                item.setData(Qt.ItemDataRole.UserRole, field_name)
                self.single_ai_suggestion_table.setItem(row_index, col, item)
            apply_item = QTableWidgetItem()
            if can_apply:
                apply_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                apply_item.setCheckState(Qt.CheckState.Unchecked)
            else:
                apply_item.setText("暂不支持应用")
                apply_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            apply_item.setData(Qt.ItemDataRole.UserRole, field_name)
            self.single_ai_suggestion_table.setItem(row_index, 3, apply_item)
            row_index += 1

    def _selected_single_ai_fields(self) -> list[str]:
        fields: list[str] = []
        for row in range(self.single_ai_suggestion_table.rowCount()):
            item = self.single_ai_suggestion_table.item(row, 3)
            if item is None or item.checkState() != Qt.CheckState.Checked:
                continue
            field_name = item.data(Qt.ItemDataRole.UserRole)
            if field_name is not None:
                fields.append(str(field_name))
        return fields

    def _current_single_ai_field_value(self, field_name: str) -> str:
        mapping = {
            "clean_title": self.series_title_edit.text(),
            "book_title": self.book_title_edit.text(),
            "volume_number": self.volume_number_edit.text(),
            "authors": self.author_edit.text(),
            "translators": self.translator_edit.text(),
            "summary": self.summary_edit.toPlainText(),
            "genres": self.genres_edit.text(),
            "tags": self.tags_edit.text(),
            "language_iso": self.language_edit.text(),
            "manga_direction": self.direction_combo.currentText(),
        }
        return mapping.get(field_name, "")

    def _refresh_single_ai_fields(self) -> None:
        book_id = self.single_saved_book_id
        if book_id is None:
            return
        book = get_book(book_id)
        work = get_work(int(book["work_id"])) if book else None
        if book and work:
            self.series_title_edit.setText(str(work.get("title") or ""))
            self.book_title_edit.setText(str(book.get("title") or ""))
            self.volume_number_edit.setText("" if book.get("volume_number") is None else str(book.get("volume_number")))
            self.author_edit.setText(str(work.get("author") or ""))
            self.summary_edit.setPlainText(str(work.get("summary") or ""))
            self.genres_edit.setText(str(work.get("genres") or ""))
            self.tags_edit.setText(str(work.get("tags") or ""))
            self.language_edit.setText(str(work.get("language_iso") or "zh"))
            self.translator_edit.setText(str(book.get("translator") or ""))
            dir_idx = self.direction_combo.findText(str(book.get("manga_direction") or "rtl"))
            if dir_idx >= 0:
                self.direction_combo.setCurrentIndex(dir_idx)
        self._populate_single_ai_suggestion_table(self.single_ai_suggestion_row)

    # ── Updated search handler using AI provider ──

    def _do_search_cover(self, book_id: int) -> None:
        search_config = load_search_config(_GuiAiRepository())
        if not search_config.enabled:
            self._show_error("联网搜索未启用，请在设置中开启。")
            return

        book = get_book(book_id)
        work = get_work(int(book["work_id"])) if book else None
        if not book or not work:
            self._show_error("找不到 book 或 work 数据。")
            return

        from app.search.search_pipeline import search_metadata_candidates
        from app.ai.title_cleaner import clean_release_title

        source_path = str(book.get("source_path", ""))
        raw_filename = Path(source_path).name if source_path else ""
        local_clean = clean_release_title(raw_filename)

        search_query = MetadataSearchQuery(
            book_id=book_id,
            title=str(work.get("title", "")).strip(),
            original_title=str(work.get("original_title", "")).strip(),
            authors=_split_terms(str(work.get("author", ""))),
            media_type="novel" if _is_novel_db_book(book) else "comic",
            language_iso=str(work.get("language_iso", "zh")).strip(),
            volume_number=book.get("volume_number"),
            raw_filename=raw_filename,
            local_clean_title=local_clean,
        )

        task_type = "search_cover"
        task_key = f"{task_type}:{book_id}"
        task_tuple = (task_type, book_id)
        if task_tuple in self._running_book_tasks:
            self.search_status_label.setText("该条目正在搜索封面/资料…")
            return

        import app.gui.workers as w

        logger.info("Search cover clicked book_id=%s title=%s", book_id, search_query.title)

        self._running_tasks.add(task_key)
        self._running_book_tasks.add(task_tuple)
        self._refresh_task_button_states(book_id)
        self.search_status_label.setText("正在后台搜索封面/资料…")

        def work() -> object:
            import time as _time
            started = _time.perf_counter()
            try:
                content_extractor = self._build_content_extractor() if search_config.ai_content_extraction_enabled else None

                result = search_metadata_candidates(
                    search_query,
                    max_candidates=search_config.max_candidates,
                    content_extractor=content_extractor,
                    book_id=book_id,
                    search_config=search_config,
                )
                row = create_metadata_search_result(
                    book_id=book_id,
                    provider=search_config.provider_type,
                    query_snapshot=asdict(search_query),
                    diagnostics_json={
                        "duration_ms": int((_time.perf_counter() - started) * 1000),
                        "providers": [asdict(diag) for diag in result.diagnostics],
                    },
                    candidates_json=[_metadata_candidate_to_dict(candidate) for candidate in result.candidates],
                    status="completed",
                )
                return row
            except Exception as exc:
                row = create_metadata_search_result(
                    book_id=book_id,
                    provider=search_config.provider_type,
                    query_snapshot=asdict(search_query),
                    diagnostics_json={"duration_ms": int((_time.perf_counter() - started) * 1000)},
                    candidates_json=[],
                    status="failed",
                    error_message=str(exc),
                )
                raise

        def on_result(_tid: str, _tname: str, _bid: object, result: object) -> None:
            if not isinstance(result, dict):
                return
            if _bid != self.current_book_id:
                logger.info("Search task completed for non-current book_id=%s current=%s", _bid, self.current_book_id)
                return
            self._display_search_result(result, expected_book_id=int(_bid), open_dialog=True)

        def on_error(_tid: str, _tname: str, _bid: object, err: str) -> None:
            if _bid != self.current_book_id:
                logger.info("Search task failed for non-current book_id=%s current=%s", _bid, self.current_book_id)
                return
            self._load_search_cache_for_book(int(_bid))
            self._show_error(f"搜索失败：{err[:200]}")

        def on_finished(_tid: str, _tname: str, _bid: object) -> None:
            self._running_tasks.discard(task_key)
            self._running_book_tasks.discard(task_tuple)
            self._active_handles.pop(_tid, None)
            if _bid == self.current_book_id:
                self._refresh_task_button_states(int(_bid))

        handle = w.submit_background_task(
            task_name="search_cover", book_id=book_id, fn=work,
            on_result=on_result, on_error=on_error, on_finished=on_finished,
        )
        self._active_handles[handle.task_id] = handle

    def _show_search_diagnostics(self, result, query_title: str = "") -> None:
        lines = [f"搜索「{query_title}」未找到匹配结果。\n"]
        lines.append("各 provider 状态：")
        for d in result.diagnostics:
            if d.enabled:
                status = d.error or f"{d.candidate_count} 个候选"
            else:
                status = d.error or "已跳过"
            lines.append(f"  • {d.name}: {status}")
        lines.append("")
        lines.append("可能原因与建议：")
        lines.append("  • 请填写作品 original_title（日文原名）或作者名以提高命中率")
        lines.append("  • 配置 GOOGLE_BOOKS_API_KEY 环境变量避免 Google Books 限流")
        lines.append("  • 配置搜索 API（Brave/Bing/SerpAPI/Tavily）获取更多数据源")
        lines.append("  • 可手动粘贴封面图片 URL")

        msg = QMessageBox(self)
        msg.setWindowTitle("搜索封面/资料 — 诊断")
        msg.setIcon(QMessageBox.Icon.Information)
        msg.setText("\n".join(lines))
        manual_btn = msg.addButton("手动粘贴封面 URL", QMessageBox.ButtonRole.ActionRole)
        copy_btn = msg.addButton("复制诊断信息", QMessageBox.ButtonRole.ActionRole)
        msg.addButton(QMessageBox.StandardButton.Ok)
        msg.exec()

        clicked = msg.clickedButton()
        if clicked == manual_btn:
            self._prompt_manual_cover_from_search(
                book_id=getattr(self, 'current_batch_book_id', None) or self.single_saved_book_id)
        elif clicked == copy_btn:
            self._copy_diagnostic_info()

    def _prompt_manual_cover_from_search(self, book_id: int | None) -> None:
        if book_id is None:
            return
        from PySide6.QtWidgets import QInputDialog
        url, ok = QInputDialog.getText(self, "手动粘贴封面 URL", "请输入图片链接（http/https）：")
        if ok and url.strip():
            self._apply_manual_cover(book_id, url.strip())

    def _apply_manual_cover(self, book_id: int, url: str) -> None:
        if not (url.startswith("http://") or url.startswith("https://")):
            self._show_error("图片链接必须是 http 或 https。")
            return
        try:
            from pathlib import Path as _Path
            from app.search.web_search_service import download_cover as _dl
            from app.storage.repositories import update_book_cover_override
            target = _Path("data") / "covers" / str(book_id) / "manual_cover.jpg"
            target.parent.mkdir(parents=True, exist_ok=True)
            downloaded = _dl(url, target)
            update_book_cover_override(book_id, str(downloaded))
            create_metadata_search_result(
                book_id=book_id,
                provider="manual",
                query_snapshot={"manual_cover_url": url},
                diagnostics_json={"manual": True},
                candidates_json=[
                    {
                        "title": "",
                        "cover_url": url,
                        "source_name": "手动输入",
                        "source_url": url,
                        "source_type": "manual",
                        "notes": ["manual cover url"],
                    }
                ],
                status="completed",
            )
            QMessageBox.information(self, "封面下载", "封面已下载并应用。")
            if self.single_saved_book_id == book_id:
                self.single_cover_override_path = downloaded
                self.single_cover_override_label.setText(str(downloaded))
                self._show_single_import_cover()
            else:
                self._refresh_batch_table(selected_book_id=book_id)
        except Exception as exc:
            logger.exception("Manual cover download failed")
            self._show_error(f"封面下载失败：{exc}")

    # ── Diagnostic info ──

    def _copy_diagnostic_info(self) -> None:
        import platform
        config = load_ai_provider_config(_GuiAiRepository())
        search_config = load_search_config(_GuiAiRepository())
        api_key_loaded = bool(os.environ.get(config.api_key_env, ""))

        lines = [
            "LightBook Studio 诊断信息",
            f"Python: {platform.python_version()}",
            f"数据库路径: {Path('data/lightbook.db').resolve()}",
            f"日志路径: {LOG_FILE.resolve()}",
            f"AI provider type: {config.provider_type}",
            f"AI base_url: {config.base_url}",
            f"AI model: {config.model}",
            f"AI api_key_env: {config.api_key_env}",
            f"AI api_key loaded: {api_key_loaded}",
            f"search provider type: {search_config.provider_type}",
            f"search enabled: {search_config.enabled}",
        ]
        QApplication.clipboard().setText("\n".join(lines))
        QMessageBox.information(self, "诊断信息", "诊断信息已复制到剪贴板。")

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

    def create_ai_request_log(self, **kwargs: Any) -> RowDict:
        return create_ai_request_log(**kwargs)

    def get_latest_metadata_search_result_by_book(self, book_id: int) -> RowDict | None:
        return get_latest_metadata_search_result_by_book(book_id)

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


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        if isinstance(parsed, list):
            return parsed
    return []


def _metadata_candidate_to_dict(candidate: Any) -> dict[str, Any]:
    if isinstance(candidate, dict):
        data = dict(candidate)
    else:
        data = asdict(candidate)
    raw_content = data.get("raw_content")
    if isinstance(raw_content, str) and len(raw_content) > 20000:
        data["raw_content"] = raw_content[:20000]
    return data


def _metadata_candidates_from_json(value: Any) -> list[MetadataSearchCandidate]:
    candidates: list[MetadataSearchCandidate] = []
    for item in _json_list(value):
        if not isinstance(item, dict):
            continue
        allowed = {
            "title",
            "original_title",
            "authors",
            "publisher",
            "publication_date",
            "isbn",
            "summary",
            "cover_url",
            "source_name",
            "source_url",
            "source_type",
            "genres",
            "tags",
            "confidence",
            "verified",
            "notes",
            "raw_content",
            "raw_content_type",
            "categories",
            "images",
            "extraction_json",
            "extraction_status",
            "extraction_error",
        }
        candidates.append(MetadataSearchCandidate(**{key: item.get(key) for key in allowed if key in item}))
    return candidates


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


def _splitter_sizes_from_setting(
    key: str,
    default: list[int],
    minimums: list[int] | None = None,
) -> list[int]:
    raw = get_setting(key)
    if not raw:
        return default
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return default
    if not isinstance(parsed, list) or not all(isinstance(item, int) for item in parsed):
        return default
    if not parsed:
        return default
    if minimums is not None and len(parsed) == len(minimums):
        return [max(value, minimum) for value, minimum in zip(parsed, minimums)]
    return parsed


def _form_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setMinimumWidth(104)
    label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return label


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


def _search_query_for_book(book_id: int) -> MetadataSearchQuery:
    from app.ai.title_cleaner import clean_release_title

    book = get_book(book_id)
    if book is None:
        raise LightBookError(f"book 不存在：{book_id}")
    work = get_work(int(book["work_id"]))
    if work is None:
        raise LightBookError(f"book {book_id} 找不到对应 work。")
    source_path = str(book.get("source_path", ""))
    raw_filename = Path(source_path).name if source_path else ""
    return MetadataSearchQuery(
        book_id=book_id,
        title=str(work.get("title", "")).strip(),
        original_title=str(work.get("original_title", "")).strip(),
        authors=_split_terms(str(work.get("author", ""))),
        media_type="novel" if _is_novel_db_book(book) else "comic",
        language_iso=str(work.get("language_iso", "zh")).strip(),
        volume_number=book.get("volume_number"),
        raw_filename=raw_filename,
        local_clean_title=clean_release_title(raw_filename),
    )


def _apply_safe_ai_suggestion(book_id: int, suggestion: RowDict, repository: _GuiAiRepository) -> int:
    parsed = _json_dict(suggestion.get("parsed_json"))
    book = repository.get_book(book_id)
    if book is None:
        return 0
    work = repository.get_work(int(book["work_id"]))
    if work is None:
        return 0

    work_updates: dict[str, Any] = {}
    book_updates: dict[str, Any] = {}
    applied = 0

    authors = _as_text_list(parsed.get("authors"))
    if authors and not str(work.get("author") or "").strip():
        work_updates["author"] = authors[0]
        applied += 1

    summary = str(parsed.get("summary") or "").strip()
    if summary and _summary_can_be_replaced(str(work.get("summary") or "")):
        work_updates["summary"] = summary
        applied += 1

    genres = _merge_term_text(str(work.get("genres") or ""), _as_text_list(parsed.get("genres")))
    if genres != str(work.get("genres") or ""):
        work_updates["genres"] = genres
        applied += 1

    tags = _merge_term_text(str(work.get("tags") or ""), _as_text_list(parsed.get("tags")))
    if tags != str(work.get("tags") or ""):
        work_updates["tags"] = tags
        applied += 1

    clean_title = str(parsed.get("clean_title") or "").strip()
    if clean_title and _title_has_release_noise(str(work.get("title") or "")):
        work_updates["title"] = clean_title
        applied += 1

    book_title = str(parsed.get("book_title") or "").strip()
    if book_title and book_title != str(book.get("title") or ""):
        book_updates["title"] = book_title
        applied += 1

    if work_updates:
        repository.update_work(int(work["id"]), **work_updates)
    if book_updates:
        repository.update_book(book_id, **book_updates)
    return applied


def _best_extracted_candidate(candidates: list[MetadataSearchCandidate]) -> MetadataSearchCandidate | None:
    for candidate in candidates:
        extraction = candidate.extraction_json
        match = extraction.get("match_assessment") if isinstance(extraction, dict) else {}
        if (
            candidate.extraction_status == "extracted"
            and not (isinstance(match, dict) and match.get("is_likely_same_work") is False)
        ):
            return candidate
    return candidates[0] if candidates else None


def _safe_search_apply_fields(
    book_id: int,
    candidate: MetadataSearchCandidate,
    *,
    include_cover: bool,
) -> list[str]:
    book = get_book(book_id)
    work = get_work(int(book["work_id"])) if book else None
    if not book or not work:
        return []
    fields: list[str] = []
    if candidate.authors and not str(work.get("author") or "").strip():
        fields.append("authors")
    if candidate.summary and _summary_can_be_replaced(str(work.get("summary") or "")):
        fields.append("summary")
    if candidate.genres:
        fields.append("genres")
    if candidate.tags:
        fields.append("tags")
    if include_cover and candidate.cover_url:
        fields.append("cover_url")
    return fields


def _candidate_with_merged_terms(book_id: int, candidate: MetadataSearchCandidate) -> MetadataSearchCandidate:
    book = get_book(book_id)
    work = get_work(int(book["work_id"])) if book else None
    if not work:
        return candidate
    return replace(
        candidate,
        genres=_split_terms(_merge_term_text(str(work.get("genres") or ""), candidate.genres)),
        tags=_split_terms(_merge_term_text(str(work.get("tags") or ""), candidate.tags)),
    )


def _merge_term_text(existing: str, additions: list[str]) -> str:
    values: list[str] = []
    seen: set[str] = set()
    for value in _split_terms(existing) + additions:
        key = value.casefold()
        if value and key not in seen:
            seen.add(key)
            values.append(value)
    return ", ".join(values)


def _as_text_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if value:
        return [str(value).strip()]
    return []


def _summary_can_be_replaced(summary: str) -> bool:
    text = summary.strip()
    if not text:
        return True
    low_quality = ("这是第", "本卷为《", "共 ", "元数据建议", "metadata")
    return any(part in text for part in low_quality)


def _title_has_release_noise(title: str) -> bool:
    import re

    return bool(
        re.search(r"\[(?:Kome|Kmoe|汉化|自购|DL|扫图|电子版)\]", title, re.IGNORECASE)
        or re.search(r"(?:第\s*\d+\s*卷|卷\s*\d+|[Vv]ol\.?\s*\d+|[Vv]\d+)", title)
        or re.search(r"\.(?:epub|cbz|txt|zip)$", title, re.IGNORECASE)
    )


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
