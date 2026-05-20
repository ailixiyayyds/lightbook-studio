from __future__ import annotations

from html import escape
from pathlib import Path
from uuid import uuid4

from ebooklib import epub

from app.core.models import ExporterError
from app.parsers.novel_chapter_parser import NovelChapter


class EpubExportError(ExporterError):
    """Raised when a novel EPUB cannot be exported."""


def export_novel_epub(
    *,
    series_title: str,
    book_title: str,
    volume_number: int | None,
    author: str,
    summary: str,
    language_iso: str,
    genres: list[str],
    tags: list[str],
    chapters: list[NovelChapter],
    output_path: Path,
) -> Path:
    if not chapters:
        raise EpubExportError("无法导出 EPUB：chapters 不能为空。")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    book = epub.EpubBook()
    book.set_identifier(f"urn:uuid:{uuid4()}")
    book.set_title(book_title or series_title or "Untitled")
    book.set_language(language_iso or "zh")
    if author:
        book.add_author(author)
    if summary:
        book.add_metadata("DC", "description", summary)
    for subject in _unique_terms([*genres, *tags]):
        book.add_metadata("DC", "subject", subject)
    if series_title and volume_number is not None:
        book.add_metadata(
            "OPF",
            "meta",
            series_title,
            {"property": "belongs-to-collection", "id": "lightbook-series"},
        )
        book.add_metadata(
            "OPF",
            "meta",
            "series",
            {"refines": "#lightbook-series", "property": "collection-type"},
        )
        book.add_metadata(
            "OPF",
            "meta",
            str(volume_number),
            {"refines": "#lightbook-series", "property": "group-position"},
        )

    style = epub.EpubItem(
        uid="style",
        file_name="styles/lightbook.css",
        media_type="text/css",
        content=_CSS.encode("utf-8"),
    )
    book.add_item(style)

    epub_chapters: list[epub.EpubHtml] = []
    for index, chapter in enumerate(chapters, start=1):
        item = epub.EpubHtml(
            uid=f"chapter_{index:04d}",
            title=chapter.title or f"Chapter {index}",
            file_name=f"chapters/chapter_{index:04d}.xhtml",
            lang=language_iso or "zh",
        )
        item.content = _chapter_body_html(chapter)
        item.add_item(style)
        book.add_item(item)
        epub_chapters.append(item)

    book.toc = tuple(epub.Link(item.file_name, item.title, item.id) for item in epub_chapters)
    book.spine = ["nav", *epub_chapters]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    try:
        epub.write_epub(str(output_path), book)
    except Exception as exc:
        raise EpubExportError(f"导出 EPUB 失败：{output_path}: {exc}") from exc

    return output_path


def _chapter_body_html(chapter: NovelChapter) -> str:
    title = escape(chapter.title or "正文")
    paragraphs = "\n".join(f"<p>{paragraph}</p>" for paragraph in _html_paragraphs(chapter.content))
    if not paragraphs:
        paragraphs = "<p></p>"
    return f"<section><h1>{title}</h1>{paragraphs}</section>"


def _html_paragraphs(text: str) -> list[str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    raw_paragraphs = normalized.split("\n\n")
    paragraphs: list[str] = []
    for raw_paragraph in raw_paragraphs:
        lines = [line.strip() for line in raw_paragraph.split("\n")]
        paragraph = "<br/>".join(escape(line) for line in lines if line)
        if paragraph:
            paragraphs.append(paragraph)
    return paragraphs


def _unique_terms(terms: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for term in terms:
        cleaned = term.strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
    return result


_CSS = """
html {
  writing-mode: horizontal-tb;
}

body {
  font-family: "Noto Serif CJK SC", "Source Han Serif SC", "Songti SC", serif;
  line-height: 1.85;
  margin: 5%;
  color: #1d1d1f;
}

h1 {
  font-size: 1.35em;
  line-height: 1.5;
  margin: 0 0 1.5em;
  text-align: center;
}

p {
  margin: 0 0 0.85em;
  text-indent: 2em;
}
""".strip()
