from __future__ import annotations

import logging
from pathlib import Path

from app.core.models import ComicMetadata, ComicPage, ImportResult, ImporterError
from app.utils.image_utils import is_supported_image_path, normalize_image_extension
from app.utils.natural_sort import natural_sorted

logger = logging.getLogger(__name__)


def import_image_folder(folder_path: str | Path) -> ImportResult:
    folder = Path(folder_path)
    if not folder.exists():
        raise ImporterError(f"图片文件夹不存在：{folder}")
    if not folder.is_dir():
        raise ImporterError(f"路径不是文件夹：{folder}")

    image_files = [
        path
        for path in folder.iterdir()
        if path.is_file() and is_supported_image_path(path)
    ]
    image_files = natural_sorted(image_files, key=lambda path: path.name)

    if not image_files:
        raise ImporterError("图片文件夹中没有找到 jpg、jpeg、png 或 webp 图片。")

    pages = [
        ComicPage(
            display_name=path.name,
            extension=normalize_image_extension(path),
            source_path=path,
        )
        for path in image_files
    ]

    try:
        cover_data = image_files[0].read_bytes()
    except OSError as exc:
        raise ImporterError(f"无法读取封面图片：{image_files[0]}") from exc

    metadata = ComicMetadata(
        series_title=folder.name,
        book_title=folder.name,
        language_iso="zh",
        manga_direction="rtl",
    )

    logger.info("Imported image folder %s with %s pages", folder, len(pages))
    return ImportResult(
        source_path=folder,
        source_type="image_folder",
        pages=pages,
        cover_data=cover_data,
        cover_extension=pages[0].extension,
        metadata=metadata,
    )
