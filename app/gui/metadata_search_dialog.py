from __future__ import annotations

import json
import logging
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.search.types import MetadataSearchCandidate, source_type_label
from app.search.web_search_service import download_cover

logger = logging.getLogger(__name__)

APPLYABLE_FIELDS = [
    ("title", "标题"),
    ("original_title", "原名"),
    ("authors", "作者"),
    ("publisher", "出版社"),
    ("publication_date", "出版日期"),
    ("summary", "简介"),
    ("genres", "分类"),
    ("tags", "标签"),
    ("cover_url", "封面"),
]


class MetadataSearchDialog(QDialog):
    def __init__(self, candidates: list[MetadataSearchCandidate], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("封面/资料搜索结果")
        self.resize(1200, 800)
        self.candidates = candidates
        self.selected_candidate: MetadataSearchCandidate | None = None
        self.manual_cover_url: str | None = None
        self._applied_signals: list[str] = []
        self._raw_content_expanded = False
        self._extraction_json_expanded = False

        self._build_ui()
        self._populate_list()

    def chosen_candidate(self) -> MetadataSearchCandidate | None:
        return self.selected_candidate

    def chosen_fields(self) -> list[str]:
        return [name for name, _cb in self.field_checkboxes.items() if _cb.isChecked()]

    def _build_ui(self) -> None:
        # Left: candidate list
        self.candidate_list = QListWidget()
        self.candidate_list.setMinimumWidth(280)
        self.candidate_list.setMaximumWidth(400)
        self.candidate_list.currentItemChanged.connect(self._on_selection_changed)

        # Right: detail panel
        self.detail_title = QLabel("请选择候选")
        self.detail_title.setWordWrap(True)
        self.detail_title.setStyleSheet("font-size: 15px; font-weight: bold;")

        self.detail_orig_title = QLabel("")
        self.detail_authors = QLabel("")
        self.detail_publisher = QLabel("")
        self.detail_publication_date = QLabel("")

        self.detail_summary = QTextEdit()
        self.detail_summary.setReadOnly(True)
        self.detail_summary.setMinimumHeight(100)
        self.detail_summary.setMaximumHeight(200)

        self.detail_genres = QLabel("")
        self.detail_genres.setWordWrap(True)
        self.detail_tags = QLabel("")
        self.detail_tags.setWordWrap(True)

        # Match assessment badge
        self.detail_match_badge = QLabel("")
        self.detail_match_badge.setStyleSheet("color: #d32f2f; font-weight: bold;")
        self.detail_match_badge.setWordWrap(True)

        # Cover section
        self.detail_cover_url = QLabel("")
        self.detail_cover_url.setWordWrap(True)
        self.detail_cover_url.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.detail_cover = QLabel("无封面")
        self.detail_cover.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detail_cover.setMinimumSize(160, 180)
        self.detail_cover.setMaximumHeight(240)
        self.detail_cover.setStyleSheet("border: 1px solid #c8c8c8; background: #fafafa;")
        self.detail_cover.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.detail_source = QLabel("")
        self.detail_source.setWordWrap(True)
        self.detail_source.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        # Source action buttons
        source_buttons = QHBoxLayout()
        self.open_source_btn = QPushButton("打开来源网页")
        self.open_source_btn.clicked.connect(self._open_source_url)
        self.open_source_btn.setEnabled(False)
        self.copy_source_btn = QPushButton("复制来源 URL")
        self.copy_source_btn.clicked.connect(self._copy_source_url)
        self.copy_source_btn.setEnabled(False)
        self.copy_cover_btn = QPushButton("复制封面 URL")
        self.copy_cover_btn.clicked.connect(self._copy_cover_url)
        self.copy_cover_btn.setEnabled(False)
        source_buttons.addWidget(self.open_source_btn)
        source_buttons.addWidget(self.copy_source_btn)
        source_buttons.addWidget(self.copy_cover_btn)
        source_buttons.addStretch()

        cover_layout = QVBoxLayout()
        cover_layout.addWidget(self.detail_cover)
        cover_layout.addWidget(self.detail_cover_url)
        cover_layout.addWidget(self.detail_source)
        cover_layout.addLayout(source_buttons)

        # Raw content preview (collapsible)
        raw_content_group = QGroupBox("页面原始内容")
        raw_content_layout = QVBoxLayout()
        self.detail_raw_content_preview = QTextEdit()
        self.detail_raw_content_preview.setReadOnly(True)
        self.detail_raw_content_preview.setMaximumHeight(150)
        self.detail_raw_content_preview.setStyleSheet("font-size: 12px; color: #555;")
        self.detail_raw_content_type = QLabel("")
        self.detail_raw_content_type.setStyleSheet("font-size: 11px; color: #888;")
        self.toggle_raw_content_btn = QPushButton("展开/收起原始内容")
        self.toggle_raw_content_btn.clicked.connect(self._toggle_raw_content)
        self.toggle_raw_content_btn.setVisible(False)
        self.view_raw_api_btn = QPushButton("查看完整 API 内容")
        self.view_raw_api_btn.clicked.connect(self._view_raw_api_content)
        self.view_raw_api_btn.setVisible(False)
        raw_content_layout.addWidget(self.detail_raw_content_type)
        raw_content_layout.addWidget(self.detail_raw_content_preview)
        raw_content_btns = QHBoxLayout()
        raw_content_btns.addWidget(self.toggle_raw_content_btn)
        raw_content_btns.addWidget(self.view_raw_api_btn)
        raw_content_btns.addStretch()
        raw_content_layout.addLayout(raw_content_btns)
        raw_content_group.setLayout(raw_content_layout)

        # AI extraction results section
        extraction_group = QGroupBox("AI 抽取结果")
        extraction_layout = QVBoxLayout()

        self.detail_extraction_status = QLabel("")
        self.detail_extraction_status.setStyleSheet("font-size: 11px;")

        self.detail_extraction_summary = QLabel("")
        self.detail_extraction_summary.setWordWrap(True)

        self.detail_extraction_genres = QLabel("")
        self.detail_extraction_genres.setWordWrap(True)
        self.detail_extraction_tags = QLabel("")
        self.detail_extraction_tags.setWordWrap(True)

        self.detail_extraction_match_reason = QLabel("")
        self.detail_extraction_match_reason.setWordWrap(True)
        self.detail_extraction_match_reason.setStyleSheet("font-size: 12px; color: #1565c0;")

        self.view_extraction_json_btn = QPushButton("查看 AI 抽取 JSON")
        self.view_extraction_json_btn.clicked.connect(self._view_extraction_json)
        self.view_extraction_json_btn.setVisible(False)

        extraction_form = QFormLayout()
        extraction_form.setSpacing(6)
        extraction_form.addRow("状态", self.detail_extraction_status)
        extraction_form.addRow("匹配判定", self.detail_extraction_match_reason)
        extraction_form.addRow("简介", self.detail_extraction_summary)
        extraction_form.addRow("分类", self.detail_extraction_genres)
        extraction_form.addRow("标签", self.detail_extraction_tags)
        extraction_layout.addLayout(extraction_form)
        extraction_layout.addWidget(self.view_extraction_json_btn)
        extraction_group.setLayout(extraction_layout)

        # Main form
        detail_form = QFormLayout()
        detail_form.setSpacing(8)
        detail_form.addRow("标题", self.detail_title)
        detail_form.addRow("原名", self.detail_orig_title)
        detail_form.addRow("作者", self.detail_authors)
        detail_form.addRow("出版社", self.detail_publisher)
        detail_form.addRow("出版日期", self.detail_publication_date)
        detail_form.addRow("简介", self.detail_summary)
        detail_form.addRow("分类", self.detail_genres)
        detail_form.addRow("标签", self.detail_tags)
        detail_form.addRow("", self.detail_match_badge)
        detail_form.addRow("封面", cover_layout)

        detail_widget = QWidget()
        detail_layout = QVBoxLayout()
        detail_layout.setSpacing(6)
        detail_layout.addLayout(detail_form)
        detail_layout.addWidget(raw_content_group)
        detail_layout.addWidget(extraction_group)
        detail_layout.addStretch()
        detail_widget.setLayout(detail_layout)

        detail_scroll = QScrollArea()
        detail_scroll.setWidgetResizable(True)
        detail_scroll.setWidget(detail_widget)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.candidate_list)
        splitter.addWidget(detail_scroll)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        # Field checkboxes
        self.field_checkboxes: dict[str, QCheckBox] = {}
        field_group = QGroupBox("应用字段")
        field_layout = QHBoxLayout()
        for field_name, field_label in APPLYABLE_FIELDS:
            cb = QCheckBox(field_label)
            cb.setChecked(False)
            self.field_checkboxes[field_name] = cb
            field_layout.addWidget(cb)
        field_layout.addStretch()
        field_group.setLayout(field_layout)

        # Manual URL area
        url_group = QGroupBox("手动图片链接")
        url_layout = QHBoxLayout()
        self.manual_url_edit = QLineEdit()
        self.manual_url_edit.setPlaceholderText("粘贴图片 URL…")
        self.manual_download_btn = QPushButton("下载并应用封面")
        self.manual_download_btn.clicked.connect(self._manual_download_cover)
        self.manual_download_btn.setEnabled(False)
        self.manual_url_edit.textChanged.connect(
            lambda t: self.manual_download_btn.setEnabled(
                bool(t.strip().startswith("http://") or t.strip().startswith("https://"))
            )
        )
        url_layout.addWidget(self.manual_url_edit)
        url_layout.addWidget(self.manual_download_btn)
        url_group.setLayout(url_layout)

        # Action buttons row
        action_layout = QHBoxLayout()
        self.apply_sel_btn = QPushButton("应用选中字段")
        self.apply_sel_btn.clicked.connect(self._apply_selected)
        self.apply_sel_btn.setEnabled(False)

        self.one_click_btn = QPushButton("一键应用推荐结果")
        self.one_click_btn.clicked.connect(self._one_click_apply)
        self.one_click_btn.setEnabled(False)

        self.close_btn = QPushButton("关闭")
        self.close_btn.clicked.connect(self.accept)

        action_layout.addWidget(self.apply_sel_btn)
        action_layout.addWidget(self.one_click_btn)
        action_layout.addStretch()
        action_layout.addWidget(self.close_btn)

        root = QVBoxLayout()
        root.setSpacing(10)
        root.setContentsMargins(12, 12, 12, 12)
        root.addWidget(splitter)
        root.addWidget(field_group)
        root.addWidget(url_group)
        root.addLayout(action_layout)
        self.setLayout(root)

    def _populate_list(self) -> None:
        for candidate in self.candidates:
            verified_mark = " ✓" if candidate.verified else ""
            has_cover = " [封面]" if candidate.cover_url else ""
            has_summary = " [简介]" if candidate.summary else ""
            no_cover = " [无封面]" if not candidate.cover_url and candidate.raw_content else ""

            # Check match assessment
            mismatch = ""
            extraction = candidate.extraction_json
            if isinstance(extraction, dict):
                match = extraction.get("match_assessment", {})
                if isinstance(match, dict) and match.get("is_likely_same_work") is False:
                    mismatch = " [可能不匹配]"

            stype = source_type_label(candidate.source_type)
            label = f"[{candidate.source_name}] {candidate.title}{verified_mark}{has_cover}{has_summary}{no_cover}{mismatch}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, id(candidate))
            tip = f"类型：{stype}\n来源：{candidate.source_name}\n{candidate.source_url}"
            if candidate.verified:
                tip = "已验证来源\n" + tip
            if mismatch:
                tip += "\n⚠ AI 判定可能不是同一作品"
            item.setToolTip(tip)
            self.candidate_list.addItem(item)

    def _on_selection_changed(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None = None) -> None:
        if current is None:
            return
        candidate_id = current.data(Qt.ItemDataRole.UserRole)
        candidate = next((c for c in self.candidates if id(c) == candidate_id), None)
        if candidate is None:
            return

        self.selected_candidate = candidate
        verified_badge = " [已验证来源]" if candidate.verified else ""
        stype = source_type_label(candidate.source_type)
        self.detail_title.setText(f"{candidate.title}{verified_badge}")
        self.detail_orig_title.setText(candidate.original_title or "—")
        self.detail_authors.setText(", ".join(candidate.authors) if candidate.authors else "未知")
        self.detail_publisher.setText(candidate.publisher or "—")
        self.detail_publication_date.setText(candidate.publication_date or "—")
        self.detail_summary.setPlainText(candidate.summary or "无简介")
        self.detail_genres.setText(", ".join(candidate.genres) if candidate.genres else "无")
        self.detail_tags.setText(", ".join(candidate.tags) if candidate.tags else "无")

        # Cover info
        if candidate.cover_url:
            self.detail_cover_url.setText(candidate.cover_url)
            self._load_cover_preview(candidate.cover_url)
            self.copy_cover_btn.setEnabled(True)
        else:
            self.detail_cover_url.setText("无封面链接" if not candidate.raw_content else "有资料，无封面")
            self.detail_cover.clear()
            self.detail_cover.setText("无封面" if not candidate.raw_content else "有资料\n无封面")
            self.copy_cover_btn.setEnabled(False)

        info_parts = [f"来源：{candidate.source_name}（{stype}）"]
        if candidate.publisher:
            info_parts.append(f"出版社：{candidate.publisher}")
        if candidate.isbn:
            info_parts.append(f"ISBN：{candidate.isbn}")
        self.detail_source.setText(" | ".join(info_parts))

        self.open_source_btn.setEnabled(bool(candidate.source_url))
        self.copy_source_btn.setEnabled(bool(candidate.source_url))
        self.apply_sel_btn.setEnabled(True)
        self.one_click_btn.setEnabled(True)

        # Match assessment badge
        extraction = candidate.extraction_json
        mismatch = False
        match_reason = ""
        if isinstance(extraction, dict):
            match = extraction.get("match_assessment", {})
            if isinstance(match, dict):
                if match.get("is_likely_same_work") is False:
                    mismatch = True
                match_reason = str(match.get("reason", ""))

        if mismatch:
            self.detail_match_badge.setText("⚠ AI 判定：可能不是同一作品")
        else:
            self.detail_match_badge.setText("")

        # Raw content preview
        raw = candidate.raw_content
        if raw:
            preview = raw[:1000]
            if len(raw) > 1000:
                preview += "\n…[已截断]"
            self.detail_raw_content_preview.setPlainText(preview)
            self.detail_raw_content_type.setText(f"内容类型：{candidate.raw_content_type or 'unknown'} | 长度：{len(raw)} 字")
            self.toggle_raw_content_btn.setVisible(len(raw) > 1000)
            self.view_raw_api_btn.setVisible(True)
        else:
            self.detail_raw_content_preview.setPlainText("（无原始内容）")
            self.detail_raw_content_type.setText("")
            self.toggle_raw_content_btn.setVisible(False)
            self.view_raw_api_btn.setVisible(False)

        # AI extraction results
        self._update_extraction_display(candidate)

    def _update_extraction_display(self, candidate: MetadataSearchCandidate) -> None:
        status = candidate.extraction_status
        if not status:
            self.detail_extraction_status.setText("尚未抽取。请配置 AI API Key 后重新搜索，或使用已抽取缓存。")
            self.detail_extraction_summary.setText("")
            self.detail_extraction_genres.setText("")
            self.detail_extraction_tags.setText("")
            self.detail_extraction_match_reason.setText("")
            self.view_extraction_json_btn.setVisible(False)
            return

        if status == "extracted":
            self.detail_extraction_status.setText("✓ 已抽取")
            self.detail_extraction_status.setStyleSheet("font-size: 11px; color: #2e7d32;")
        elif status == "extracting":
            self.detail_extraction_status.setText("正在 AI 抽取...")
            self.detail_extraction_status.setStyleSheet("font-size: 11px; color: #1565c0;")
        elif status == "failed":
            self.detail_extraction_status.setText(f"✗ 抽取失败：{candidate.extraction_error[:200]}")
            self.detail_extraction_status.setStyleSheet("font-size: 11px; color: #c62828;")
            self.detail_extraction_summary.setText("")
            self.detail_extraction_genres.setText("")
            self.detail_extraction_tags.setText("")
            self.detail_extraction_match_reason.setText("")
            self.view_extraction_json_btn.setVisible(False)
            return
        else:
            self.detail_extraction_status.setText("尚未抽取。请点击“重新搜索”或配置 AI 后再次搜索。")
            self.detail_extraction_status.setStyleSheet("font-size: 11px; color: #e65100;")

        extraction = candidate.extraction_json
        if isinstance(extraction, dict):
            self.detail_extraction_summary.setText(
                str(extraction.get("summary_zh") or extraction.get("summary") or "") or "无"
            )
            self.detail_extraction_genres.setText(", ".join(extraction.get("genres", [])) or "无")
            self.detail_extraction_tags.setText(", ".join(extraction.get("tags", [])) or "无")
            match = extraction.get("match_assessment", {})
            if isinstance(match, dict):
                is_match = match.get("is_likely_same_work", True)
                reason = str(match.get("reason", ""))
                if is_match is False:
                    self.detail_extraction_match_reason.setText(f"⚠ 不匹配：{reason}")
                    self.detail_extraction_match_reason.setStyleSheet("font-size: 12px; color: #c62828;")
                else:
                    self.detail_extraction_match_reason.setText(reason or "匹配")
                    self.detail_extraction_match_reason.setStyleSheet("font-size: 12px; color: #2e7d32;")
            self.view_extraction_json_btn.setVisible(True)
        else:
            self.detail_extraction_summary.setText("")
            self.detail_extraction_genres.setText("")
            self.detail_extraction_tags.setText("")
            self.detail_extraction_match_reason.setText("")
            self.view_extraction_json_btn.setVisible(False)

    def _toggle_raw_content(self) -> None:
        if self.selected_candidate is None:
            return
        self._raw_content_expanded = not self._raw_content_expanded
        if self._raw_content_expanded:
            self.detail_raw_content_preview.setMaximumHeight(400)
            self.detail_raw_content_preview.setPlainText(self.selected_candidate.raw_content)
        else:
            self.detail_raw_content_preview.setMaximumHeight(150)
            preview = self.selected_candidate.raw_content[:1000]
            if len(self.selected_candidate.raw_content) > 1000:
                preview += "\n…[已截断]"
            self.detail_raw_content_preview.setPlainText(preview)

    def _view_raw_api_content(self) -> None:
        if self.selected_candidate is None or not self.selected_candidate.raw_content:
            return
        dialog = _RawContentDialog(
            "原始 API 内容",
            self.selected_candidate.raw_content,
            self,
        )
        dialog.exec()

    def _view_extraction_json(self) -> None:
        if self.selected_candidate is None or not self.selected_candidate.extraction_json:
            return
        dialog = _RawContentDialog(
            "AI 抽取 JSON",
            json.dumps(self.selected_candidate.extraction_json, ensure_ascii=False, indent=2),
            self,
        )
        dialog.exec()

    def _load_cover_preview(self, cover_url: str) -> None:
        try:
            import httpx
            response = httpx.get(cover_url, timeout=10, follow_redirects=True)
            if response.status_code < 200 or response.status_code >= 300:
                self.detail_cover.setText(f"封面加载失败 HTTP {response.status_code}")
                return
            pixmap = QPixmap()
            pixmap.loadFromData(response.content)
            if pixmap.isNull():
                self.detail_cover.setText("无法加载封面")
            else:
                self.detail_cover.setPixmap(
                    pixmap.scaled(
                        self.detail_cover.size(),
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
        except Exception as exc:
            logger.debug("Failed to load cover preview url=%s: %s", cover_url, exc)
            self.detail_cover.setText("封面加载失败")

    def _open_source_url(self) -> None:
        if self.selected_candidate and self.selected_candidate.source_url:
            QDesktopServices.openUrl(QUrl(self.selected_candidate.source_url))

    def _copy_source_url(self) -> None:
        if self.selected_candidate and self.selected_candidate.source_url:
            QApplication.clipboard().setText(self.selected_candidate.source_url)

    def _copy_cover_url(self) -> None:
        if self.selected_candidate and self.selected_candidate.cover_url:
            QApplication.clipboard().setText(self.selected_candidate.cover_url)

    def _apply_selected(self) -> None:
        if self.selected_candidate is None:
            return
        fields = self.chosen_fields()
        if not fields:
            QMessageBox.information(self, "提示", "请先勾选要应用的字段。")
            return
        self._applied_signals.append("selected_fields")

    def _one_click_apply(self) -> None:
        if self.selected_candidate is None:
            return
        for cb in self.field_checkboxes.values():
            cb.setChecked(False)

        candidate = self.selected_candidate
        self.field_checkboxes["summary"].setChecked(bool(candidate.summary))
        self.field_checkboxes["genres"].setChecked(bool(candidate.genres))
        self.field_checkboxes["tags"].setChecked(bool(candidate.tags))

        if candidate.authors:
            self.field_checkboxes["authors"].setChecked(True)
        if candidate.publisher:
            self.field_checkboxes["publisher"].setChecked(True)
        if candidate.original_title:
            self.field_checkboxes["original_title"].setChecked(True)
        if candidate.publication_date:
            self.field_checkboxes["publication_date"].setChecked(True)

        if _title_looks_noisy(candidate.title):
            self.field_checkboxes["title"].setChecked(True)

        if candidate.cover_url:
            self.field_checkboxes["cover_url"].setChecked(True)

        self._applied_signals.append("one_click")

    def _manual_download_cover(self) -> None:
        url = self.manual_url_edit.text().strip()
        if not url:
            return
        if not (url.startswith("http://") or url.startswith("https://")):
            QMessageBox.warning(self, "错误", "图片链接必须是 http 或 https。")
            return
        self.manual_cover_url = url
        self._applied_signals.append("manual_cover")


class _RawContentDialog(QDialog):
    """Simple dialog to display raw content or JSON."""

    def __init__(self, title: str, content: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(700, 500)

        layout = QVBoxLayout()
        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setPlainText(content)
        text_edit.setStyleSheet("font-family: monospace; font-size: 12px;")

        copy_btn = QPushButton("复制到剪贴板")
        copy_btn.clicked.connect(lambda: QApplication.clipboard().setText(content))

        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)

        btn_layout = QHBoxLayout()
        btn_layout.addWidget(copy_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(close_btn)

        layout.addWidget(text_edit)
        layout.addLayout(btn_layout)
        self.setLayout(layout)


def _title_looks_noisy(title: str) -> bool:
    import re
    if re.search(r"\[(?:Kome|Kmoe|汉化|自购|DL|扫图|电子版)\]", title):
        return True
    if re.search(r"第\s*\d+\s*卷|[Vv]\d{2,}", title):
        return True
    if re.search(r"\.(?:epub|cbz|txt|zip)$", title, re.IGNORECASE):
        return True
    return False
