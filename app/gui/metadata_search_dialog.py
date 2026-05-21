from __future__ import annotations

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
    QInputDialog,
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
    ("authors", "作者"),
    ("summary", "简介"),
    ("genres", "分类"),
    ("tags", "标签"),
    ("cover_url", "封面"),
]


class MetadataSearchDialog(QDialog):
    def __init__(self, candidates: list[MetadataSearchCandidate], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("封面/资料搜索结果")
        self.resize(1100, 750)
        self.candidates = candidates
        self.selected_candidate: MetadataSearchCandidate | None = None
        self.manual_cover_url: str | None = None
        self._applied_signals: list[str] = []

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

        self.detail_summary = QTextEdit()
        self.detail_summary.setReadOnly(True)
        self.detail_summary.setMinimumHeight(120)

        self.detail_genres = QLabel("")
        self.detail_genres.setWordWrap(True)
        self.detail_tags = QLabel("")
        self.detail_tags.setWordWrap(True)

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

        # Source action buttons
        source_buttons = QHBoxLayout()
        self.open_source_btn = QPushButton("打开来源网页")
        self.open_source_btn.clicked.connect(self._open_source_url)
        self.open_source_btn.setEnabled(False)
        self.copy_cover_btn = QPushButton("复制封面链接")
        self.copy_cover_btn.clicked.connect(self._copy_cover_url)
        self.copy_cover_btn.setEnabled(False)
        source_buttons.addWidget(self.open_source_btn)
        source_buttons.addWidget(self.copy_cover_btn)
        source_buttons.addStretch()

        cover_layout = QVBoxLayout()
        cover_layout.addWidget(self.detail_cover)
        cover_layout.addWidget(self.detail_cover_url)
        cover_layout.addWidget(self.detail_source)
        cover_layout.addLayout(source_buttons)

        detail_form = QFormLayout()
        detail_form.setSpacing(8)
        detail_form.addRow("标题", self.detail_title)
        detail_form.addRow("原名", self.detail_orig_title)
        detail_form.addRow("作者", self.detail_authors)
        detail_form.addRow("简介", self.detail_summary)
        detail_form.addRow("分类", self.detail_genres)
        detail_form.addRow("标签", self.detail_tags)
        detail_form.addRow("封面", cover_layout)

        detail_widget = QWidget()
        detail_widget.setLayout(detail_form)

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
            stype = source_type_label(candidate.source_type)
            label = f"[{candidate.source_name}] {candidate.title}{verified_mark}{has_cover}{has_summary}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, id(candidate))
            tip = f"类型：{stype}\n来源：{candidate.source_name}\n{candidate.source_url}"
            if candidate.verified:
                tip = "已验证来源\n" + tip
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
        self.detail_summary.setPlainText(candidate.summary)
        self.detail_genres.setText(", ".join(candidate.genres) if candidate.genres else "无")
        self.detail_tags.setText(", ".join(candidate.tags) if candidate.tags else "无")
        self.detail_cover_url.setText(candidate.cover_url or "无封面链接")
        info_parts = [f"来源：{candidate.source_name}（{stype}）"]
        if candidate.publisher:
            info_parts.append(f"出版社：{candidate.publisher}")
        if candidate.isbn:
            info_parts.append(f"ISBN：{candidate.isbn}")
        self.detail_source.setText(" | ".join(info_parts))

        if candidate.cover_url:
            self._load_cover_preview(candidate.cover_url)
            self.copy_cover_btn.setEnabled(True)
        else:
            self.detail_cover.clear()
            self.detail_cover.setText("无封面")
            self.copy_cover_btn.setEnabled(False)

        self.open_source_btn.setEnabled(bool(candidate.source_url))
        self.apply_sel_btn.setEnabled(True)
        self.one_click_btn.setEnabled(True)

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
        # Don't close — caller handles logic via signals

    def _one_click_apply(self) -> None:
        if self.selected_candidate is None:
            return
        # Auto-select summary, genres, tags. Optionally author if empty, title if noisy.
        for cb in self.field_checkboxes.values():
            cb.setChecked(False)

        self.field_checkboxes["summary"].setChecked(True)
        self.field_checkboxes["genres"].setChecked(True)
        self.field_checkboxes["tags"].setChecked(True)

        candidate = self.selected_candidate
        if not candidate.authors:
            self.field_checkboxes["authors"].setChecked(False)
        else:
            self.field_checkboxes["authors"].setChecked(True)

        if _title_looks_noisy(candidate.title):
            self.field_checkboxes["title"].setChecked(True)
        else:
            self.field_checkboxes["title"].setChecked(False)

        if candidate.cover_url:
            self.field_checkboxes["cover_url"].setChecked(True)
        else:
            self.field_checkboxes["cover_url"].setChecked(False)

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


def _title_looks_noisy(title: str) -> bool:
    import re
    if re.search(r"\[(?:Kome|Kmoe|汉化|自购|DL|扫图|电子版)\]", title):
        return True
    if re.search(r"第\s*\d+\s*卷|[Vv]\d{2,}", title):
        return True
    if re.search(r"\.(?:epub|cbz|txt|zip)$", title, re.IGNORECASE):
        return True
    return False
