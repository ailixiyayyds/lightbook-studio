from __future__ import annotations

import logging
import posixpath
import zipfile
from pathlib import Path
from typing import cast
from xml.etree import ElementTree as ET

from app.core.models import ComicMetadata, ComicPage, ImportResult, ImporterError, MangaDirection
from app.utils.filename_parser import parse_comic_filename
from app.utils.image_utils import is_supported_image_path, normalize_image_extension
from app.utils.natural_sort import natural_sorted

logger = logging.getLogger(__name__)


class CbzImporter:
    def import_file(self, path: str | Path) -> ImportResult:
        return import_cbz(path)


def import_cbz(cbz_path: str | Path) -> ImportResult:
    path = Path(cbz_path)
    if not path.exists():
        raise ImporterError(f"CBZ 文件不存在：{path}")
    if not path.is_file():
        raise ImporterError(f"路径不是 CBZ 文件：{path}")
    if path.suffix.casefold() != ".cbz":
        raise ImporterError(f"文件不是 .cbz：{path}")

    try:
        with zipfile.ZipFile(path) as archive:
            image_paths = _image_paths(archive)
            if not image_paths:
                raise ImporterError(f"CBZ 中没有找到可导入的图片：{path}")

            comicinfo_path = _find_comicinfo_path(archive)
            if comicinfo_path is not None:
                metadata = _parse_comicinfo(archive.read(comicinfo_path))
            else:
                metadata = _metadata_from_filename(path.name)

            pages = _build_pages(path, image_paths)
            cover_data = archive.read(pages[0].archive_path or "")
    except zipfile.BadZipFile as exc:
        raise ImporterError(f"CBZ 不是有效的 ZIP 文件：{path}") from exc
    except ET.ParseError as exc:
        raise ImporterError(f"ComicInfo.xml 解析失败：{exc}") from exc
    except OSError as exc:
        raise ImporterError(f"读取 CBZ 失败：{exc}") from exc

    logger.info("Imported CBZ %s with %s pages", path, len(pages))
    return ImportResult(
        source_path=path,
        source_type="cbz",
        pages=pages,
        cover_data=cover_data,
        cover_extension=pages[0].extension,
        metadata=metadata,
        warnings=[],
    )


def _image_paths(archive: zipfile.ZipFile) -> list[str]:
    return natural_sorted(
        name
        for name in archive.namelist()
        if not name.endswith("/") and is_supported_image_path(name)
    )


def _build_pages(cbz_path: Path, image_paths: list[str]) -> list[ComicPage]:
    return [
        ComicPage(
            display_name=posixpath.basename(path),
            extension=normalize_image_extension(path),
            source_path=cbz_path,
            archive_path=path,
        )
        for path in image_paths
    ]


def _find_comicinfo_path(archive: zipfile.ZipFile) -> str | None:
    names = archive.namelist()
    for name in names:
        if name == "ComicInfo.xml":
            return name
    for name in names:
        if posixpath.basename(name).casefold() == "comicinfo.xml":
            return name
    return None


def _parse_comicinfo(xml_bytes: bytes) -> ComicMetadata:
    root = ET.fromstring(xml_bytes)
    number_text = _first_text(root, "Number")
    return ComicMetadata(
        series_title=_first_text(root, "Series"),
        book_title=_first_text(root, "Title"),
        volume_number=_parse_int(number_text, fallback=1),
        author=_first_text(root, "Writer"),
        translator=_first_text(root, "Translator"),
        summary=_first_text(root, "Summary"),
        genres=_split_terms(_first_text(root, "Genre")),
        tags=_split_terms(_first_text(root, "Tags")),
        language_iso=_first_text(root, "LanguageISO") or "zh",
        manga_direction=_parse_manga_direction(_first_text(root, "Manga")),
    )


def _metadata_from_filename(name: str) -> ComicMetadata:
    parsed = parse_comic_filename(name)
    series_title = parsed.series_title or parsed.book_title
    book_title = parsed.book_title or series_title
    return ComicMetadata(
        series_title=series_title,
        book_title=book_title,
        volume_number=parsed.volume_number or 1,
        language_iso="zh",
    )


def _first_text(root: ET.Element, local_name: str) -> str:
    for element in root.iter():
        if _local_name(element.tag) == local_name and element.text:
            return element.text.strip()
    return ""


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag


def _split_terms(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _parse_int(value: str, *, fallback: int) -> int:
    if not value.strip():
        return fallback
    try:
        return int(float(value.strip()))
    except ValueError:
        return fallback


def _parse_manga_direction(value: str) -> MangaDirection:
    normalized = value.strip()
    if normalized == "YesAndRightToLeft":
        return "rtl"
    if normalized == "No":
        return "ltr"
    if normalized == "Unknown":
        return "webtoon"
    return cast(MangaDirection, "rtl")
