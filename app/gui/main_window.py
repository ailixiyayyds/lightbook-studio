from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.core.config import AppConfig, load_config, save_config
from app.core.models import ComicMetadata, ImportResult, LightBookError
from app.exporters.cbz_exporter import export_cbz
from app.importers.comic_epub_importer import import_comic_epub
from app.importers.image_folder_importer import import_image_folder

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("LightBook Studio")
        self.resize(980, 720)

        self.config = load_config()
        self.import_result: ImportResult | None = None
        self.output_root = Path(self.config.recent_output_dir) if self.config.recent_output_dir else None

        self.source_label = QLabel("未选择")
        self.page_count_label = QLabel("0")
        self.output_label = QLabel(str(self.output_root) if self.output_root else "未选择")
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

        self._build_ui()

    def _build_ui(self) -> None:
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
        self.setCentralWidget(container)

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
        self.output_label.setText(str(self.output_root))
        self.config.recent_output_dir = str(self.output_root)
        save_config(self.config)

    def _load_source(self, path: Path, importer: object) -> None:
        try:
            result = importer(path)  # type: ignore[operator]
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
            manga_direction=self.direction_combo.currentText(),  # type: ignore[arg-type]
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

    def _show_error(self, message: str) -> None:
        QMessageBox.critical(self, "LightBook Studio", message)


def _split_terms(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]
