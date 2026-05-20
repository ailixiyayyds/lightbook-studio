from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

import pytest
from ebooklib import epub

from app.exporters.epub_exporter import EpubExportError, export_novel_epub
from app.parsers.novel_chapter_parser import NovelChapter


def test_export_novel_epub_creates_file(tmp_path: Path) -> None:
    output_path = tmp_path / "novel.epub"

    result = export_novel_epub(
        series_title="系列",
        book_title="第一卷",
        volume_number=1,
        author="作者",
        summary="简介",
        language_iso="zh",
        genres=["奇幻"],
        tags=["校园"],
        chapters=[NovelChapter(title="序章", content="正文", order_index=1)],
        output_path=output_path,
    )

    assert result == output_path
    assert output_path.exists()
    assert output_path.stat().st_size > 0


def test_export_novel_epub_contains_chapters_and_escaped_html(tmp_path: Path) -> None:
    output_path = tmp_path / "novel.epub"

    export_novel_epub(
        series_title="系列",
        book_title="第一卷",
        volume_number=1,
        author="作者",
        summary="简介",
        language_iso="zh",
        genres=[],
        tags=[],
        chapters=[
            NovelChapter(title="序章", content="5 < 6 & 7 > 3\n\n第二段", order_index=1),
            NovelChapter(title="第一章", content="内容", order_index=2),
        ],
        output_path=output_path,
    )

    with ZipFile(output_path) as archive:
        names = set(archive.namelist())
        assert "chapters/chapter_0001.xhtml" in names
        assert "chapters/chapter_0002.xhtml" in names
        assert "nav.xhtml" in names
        chapter_html = archive.read("chapters/chapter_0001.xhtml").decode("utf-8")

    assert "5 &lt; 6 &amp; 7 &gt; 3" in chapter_html
    assert "<p>第二段</p>" in chapter_html


def test_export_novel_epub_writes_metadata(tmp_path: Path) -> None:
    output_path = tmp_path / "novel.epub"

    export_novel_epub(
        series_title="系列名",
        book_title="卷标题",
        volume_number=3,
        author="作者名",
        summary="内容简介",
        language_iso="zh",
        genres=["奇幻", "冒险"],
        tags=["标签"],
        chapters=[NovelChapter(title="序章", content="正文", order_index=1)],
        output_path=output_path,
    )

    book = epub.read_epub(str(output_path))
    assert book.get_metadata("DC", "title")[0][0] == "卷标题"
    assert book.get_metadata("DC", "creator")[0][0] == "作者名"
    assert book.get_metadata("DC", "language")[0][0] == "zh"
    assert book.get_metadata("DC", "description")[0][0] == "内容简介"
    subjects = [item[0] for item in book.get_metadata("DC", "subject")]
    assert subjects == ["奇幻", "冒险", "标签"]

    with ZipFile(output_path) as archive:
        opf = archive.read("EPUB/content.opf").decode("utf-8")
    assert 'property="belongs-to-collection"' in opf
    assert ">系列名<" in opf
    assert 'property="group-position"' in opf
    assert ">3<" in opf


def test_export_novel_epub_rejects_empty_chapters(tmp_path: Path) -> None:
    with pytest.raises(EpubExportError):
        export_novel_epub(
            series_title="系列",
            book_title="空书",
            volume_number=None,
            author="作者",
            summary="",
            language_iso="zh",
            genres=[],
            tags=[],
            chapters=[],
            output_path=tmp_path / "empty.epub",
        )
