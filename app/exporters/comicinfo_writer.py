from __future__ import annotations

from xml.etree import ElementTree as ET

from app.core.models import ComicMetadata

MANGA_DIRECTION_MAP = {
    "rtl": "YesAndRightToLeft",
    "ltr": "No",
    "webtoon": "Unknown",
}


def build_comicinfo_xml(metadata: ComicMetadata) -> bytes:
    root = ET.Element("ComicInfo")
    _add_text(root, "Series", metadata.series_title)
    _add_text(root, "Title", metadata.book_title)
    _add_text(root, "Number", str(metadata.volume_number))
    _add_text(root, "Writer", metadata.author)
    _add_text(root, "Translator", metadata.translator)
    _add_text(root, "Summary", metadata.summary)
    _add_text(root, "Genre", _join_terms(metadata.genres))
    _add_text(root, "Tags", _join_terms(metadata.tags))
    _add_text(root, "LanguageISO", metadata.language_iso or "zh")
    _add_text(root, "Manga", MANGA_DIRECTION_MAP.get(metadata.manga_direction, "Unknown"))
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _add_text(root: ET.Element, tag: str, text: str) -> None:
    element = ET.SubElement(root, tag)
    element.text = text or ""


def _join_terms(terms: list[str]) -> str:
    return ", ".join(term.strip() for term in terms if term.strip())
