from __future__ import annotations

import logging
import posixpath
import zipfile
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote
from xml.etree import ElementTree as ET

try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover - beautifulsoup4 is a declared dependency.
    BeautifulSoup = None  # type: ignore[assignment]

from app.core.models import ComicMetadata, ComicPage, ImportResult, ImporterError
from app.utils.image_utils import is_supported_image_path, normalize_image_extension
from app.utils.natural_sort import natural_sorted

logger = logging.getLogger(__name__)

CONTAINER_PATH = "META-INF/container.xml"
OPF_MEDIA_TYPE = "application/oebps-package+xml"
HTML_MEDIA_TYPES = {
    "application/xhtml+xml",
    "text/html",
    "application/x-dtbncx+xml",
}


@dataclass(frozen=True)
class _ManifestItem:
    item_id: str
    href: str
    path: str
    media_type: str
    properties: str = ""


class _ImageHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.sources: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() not in {"img", "image"}:
            return
        attr_map = {name.casefold(): value for name, value in attrs if value}
        for name in ("src", "href", "xlink:href"):
            value = attr_map.get(name)
            if value:
                self.sources.append(value)
                break


def import_comic_epub(epub_path: str | Path) -> ImportResult:
    path = Path(epub_path)
    if not path.exists():
        raise ImporterError(f"EPUB 文件不存在：{path}")
    if not path.is_file():
        raise ImporterError(f"路径不是 EPUB 文件：{path}")

    warnings: list[str] = []
    try:
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
            opf_path = _find_opf_path(zf)
            opf_root = ET.fromstring(zf.read(opf_path))
            opf_dir = posixpath.dirname(opf_path)
            manifest = _parse_manifest(opf_root, opf_dir)
            metadata = _parse_metadata(opf_root, default_title=path.stem)

            page_paths, spine_warnings = _page_paths_from_spine(zf, opf_root, manifest, names)
            warnings.extend(spine_warnings)
            if not page_paths:
                warnings.append("无法从 EPUB spine 中解析页面图片，已回退到所有图片自然排序。")
                page_paths = _fallback_image_paths(zf, manifest)

            if not page_paths:
                raise ImporterError("EPUB 中没有找到可导出的漫画图片。")

            pages = _build_pages(page_paths)
            cover_data = zf.read(pages[0].archive_path or "")
    except zipfile.BadZipFile as exc:
        raise ImporterError(f"EPUB 不是有效的 ZIP/EPUB 文件：{path}") from exc
    except ET.ParseError as exc:
        raise ImporterError(f"EPUB 元数据 XML 解析失败：{exc}") from exc
    except KeyError as exc:
        raise ImporterError(f"EPUB 缺少必要文件：{exc}") from exc
    except OSError as exc:
        raise ImporterError(f"读取 EPUB 失败：{exc}") from exc

    logger.info("Imported EPUB %s with %s pages", path, len(pages))
    return ImportResult(
        source_path=path,
        source_type="epub",
        pages=pages,
        cover_data=cover_data,
        cover_extension=pages[0].extension,
        metadata=metadata,
        warnings=warnings,
    )


def _find_opf_path(zf: zipfile.ZipFile) -> str:
    try:
        container_xml = zf.read(CONTAINER_PATH)
    except KeyError as exc:
        raise ImporterError(f"EPUB 缺少 {CONTAINER_PATH}。") from exc

    root = ET.fromstring(container_xml)
    rootfiles = [element for element in root.iter() if _local_name(element.tag) == "rootfile"]
    if not rootfiles:
        raise ImporterError("EPUB container.xml 中没有 rootfile。")

    preferred = next(
        (
            element
            for element in rootfiles
            if element.attrib.get("media-type") == OPF_MEDIA_TYPE
        ),
        rootfiles[0],
    )
    opf_path = preferred.attrib.get("full-path")
    if not opf_path:
        raise ImporterError("EPUB rootfile 缺少 full-path。")
    return opf_path


def _parse_manifest(root: ET.Element, opf_dir: str) -> dict[str, _ManifestItem]:
    manifest_element = _first_child(root, "manifest")
    if manifest_element is None:
        raise ImporterError("OPF 中缺少 manifest。")

    manifest: dict[str, _ManifestItem] = {}
    for item in manifest_element:
        if _local_name(item.tag) != "item":
            continue
        item_id = item.attrib.get("id")
        href = item.attrib.get("href")
        if not item_id or not href:
            continue
        manifest[item_id] = _ManifestItem(
            item_id=item_id,
            href=href,
            path=_resolve_path(opf_dir, href),
            media_type=item.attrib.get("media-type", ""),
            properties=item.attrib.get("properties", ""),
        )
    return manifest


def _parse_metadata(root: ET.Element, default_title: str) -> ComicMetadata:
    metadata_element = _first_child(root, "metadata")
    title = _first_text(metadata_element, "title") or default_title
    creators = _texts(metadata_element, "creator")
    subjects = _texts(metadata_element, "subject")

    return ComicMetadata(
        series_title=title,
        book_title=title,
        author=", ".join(creators),
        summary=_first_text(metadata_element, "description"),
        genres=subjects,
        tags=subjects.copy(),
        language_iso=_first_text(metadata_element, "language") or "zh",
        manga_direction="rtl",
    )


def _page_paths_from_spine(
    zf: zipfile.ZipFile,
    opf_root: ET.Element,
    manifest: dict[str, _ManifestItem],
    names: set[str],
) -> tuple[list[str], list[str]]:
    warnings: list[str] = []
    spine_element = _first_child(opf_root, "spine")
    if spine_element is None:
        return [], ["OPF 中缺少 spine。"]

    manifest_by_path = {item.path: item for item in manifest.values()}
    page_paths: list[str] = []
    seen: set[str] = set()

    for itemref in spine_element:
        if _local_name(itemref.tag) != "itemref":
            continue
        idref = itemref.attrib.get("idref")
        if not idref:
            continue
        manifest_item = manifest.get(idref)
        if manifest_item is None:
            warnings.append(f"spine 引用了不存在的 manifest id：{idref}")
            continue
        if not _is_html_item(manifest_item):
            continue
        try:
            html_bytes = zf.read(manifest_item.path)
        except KeyError:
            warnings.append(f"spine 页面文件不存在：{manifest_item.path}")
            continue

        html_dir = posixpath.dirname(manifest_item.path)
        for src in _extract_image_sources(html_bytes):
            image_path = _resolve_path(html_dir, src)
            if not image_path or image_path in seen:
                continue
            manifest_image = manifest_by_path.get(image_path)
            is_image = manifest_image is not None and manifest_image.media_type.startswith("image/")
            if (is_image or is_supported_image_path(image_path)) and image_path in names:
                seen.add(image_path)
                page_paths.append(image_path)
            else:
                warnings.append(f"spine 页面引用了无法找到的图片：{image_path}")

    return page_paths, warnings


def _fallback_image_paths(
    zf: zipfile.ZipFile,
    manifest: dict[str, _ManifestItem],
) -> list[str]:
    manifest_paths = [
        item.path
        for item in manifest.values()
        if item.media_type.startswith("image/") and is_supported_image_path(item.path)
    ]
    if manifest_paths:
        return natural_sorted(manifest_paths)

    return natural_sorted(
        name
        for name in zf.namelist()
        if not name.endswith("/") and is_supported_image_path(name)
    )


def _build_pages(page_paths: list[str]) -> list[ComicPage]:
    return [
        ComicPage(
            display_name=posixpath.basename(path),
            extension=normalize_image_extension(path),
            archive_path=path,
        )
        for path in page_paths
    ]


def _extract_image_sources(html_bytes: bytes) -> list[str]:
    if BeautifulSoup is not None:
        soup = BeautifulSoup(html_bytes, "html.parser")
        sources: list[str] = []
        for tag in soup.find_all(["img", "image"]):
            src = tag.get("src") or tag.get("href") or tag.get("xlink:href")
            if src:
                sources.append(str(src))
        return sources

    parser = _ImageHTMLParser()
    parser.feed(html_bytes.decode("utf-8", errors="ignore"))
    return parser.sources


def _resolve_path(base_dir: str, href: str) -> str:
    href_without_fragment = href.split("#", 1)[0]
    decoded = unquote(href_without_fragment).replace("\\", "/")
    if not decoded:
        return ""
    if decoded.startswith("/"):
        resolved = decoded.lstrip("/")
    else:
        resolved = posixpath.normpath(posixpath.join(base_dir, decoded))
    return resolved.replace("\\", "/")


def _is_html_item(item: _ManifestItem) -> bool:
    return item.media_type in HTML_MEDIA_TYPES or item.path.casefold().endswith((".xhtml", ".html", ".htm"))


def _first_child(root: ET.Element | None, local_name: str) -> ET.Element | None:
    if root is None:
        return None
    for child in root.iter():
        if _local_name(child.tag) == local_name:
            return child
    return None


def _texts(root: ET.Element | None, local_name: str) -> list[str]:
    if root is None:
        return []
    values: list[str] = []
    for element in root.iter():
        if _local_name(element.tag) == local_name and element.text:
            text = element.text.strip()
            if text:
                values.append(text)
    return values


def _first_text(root: ET.Element | None, local_name: str) -> str:
    values = _texts(root, local_name)
    return values[0] if values else ""


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag
