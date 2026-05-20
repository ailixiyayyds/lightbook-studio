from __future__ import annotations

from pathlib import Path

import pytest

from app.core.models import ImporterError
from app.importers.novel_txt_importer import NovelTxtImporter, import_novel_txt


WENKU8_BANNER = "★☆★☆★☆轻小说文库(Www.WenKu8.Com)☆★☆★☆★"


def test_import_novel_txt_detects_title_guess_from_full_download_header(tmp_path: Path) -> None:
    path = tmp_path / "3159 gbk.txt"
    text = "\r\n".join(
        [
            WENKU8_BANNER,
            "",
            "<灰原同学重返过去，开启所向无敌的第二轮青春游戏(灰原君的青春二周目)>",
            "",
            "第一卷 序章 青春的后悔",
            "    台版 转自 天使动漫论坛",
            "    轻之国度×天使动漫录入组",
            "    图源：Aircer",
            "    扫图：linpop",
            "    录入：kid",
            "    修图：轻之国度录入组",
            "",
            "正文第一段",
        ]
    )
    path.write_bytes(text.encode("gbk"))

    result = import_novel_txt(path)

    assert result.source_file_id == "3159"
    assert result.encoding == "gb18030"
    assert result.title_guess == "灰原同学重返过去，开启所向无敌的第二轮青春游戏"
    assert result.chapter_count == 1
    assert result.volumes[0].title == "第一卷"
    assert result.volumes[0].volume_number == 1
    assert result.volumes[0].chapters[0].title == "序章 青春的后悔"


def test_import_novel_txt_keeps_empty_title_for_split_volume_without_angle_title(tmp_path: Path) -> None:
    path = tmp_path / "139089 gbk.txt"
    text = "\n".join(
        [
            "★☆★☆★☆轻小说文库(Www.WenKu8.com)☆★☆★☆★ ",
            "",
            "  第二卷 序章 平凡无奇的初恋  ",
            "     台版 转自 轻之国度 ",
            "     轻之国度×天使动漫录入组 ",
            "     图源：Aircer ",
            "正文",
        ]
    )
    path.write_bytes(text.encode("gbk"))

    result = import_novel_txt(path)

    assert result.title_guess == ""
    assert "未能从正文推测标题。" in result.warnings
    assert result.volumes[0].title == "第二卷"
    assert result.volumes[0].volume_number == 2
    assert result.volumes[0].chapters[0].title == "序章 平凡无奇的初恋"


def test_import_novel_txt_parses_volume_and_chapter_on_same_line(tmp_path: Path) -> None:
    path = tmp_path / "novel.txt"
    path.write_text("第一卷 序章 青春的后悔\n正文", encoding="utf-8")

    result = import_novel_txt(path)

    assert result.volumes[0].title == "第一卷"
    assert result.volumes[0].volume_number == 1
    assert result.volumes[0].chapters[0].title == "序章 青春的后悔"
    assert result.volumes[0].chapters[0].content == "正文"


def test_import_novel_txt_parses_second_volume_number(tmp_path: Path) -> None:
    path = tmp_path / "novel.txt"
    path.write_text("第二卷 序章 平凡无奇的初恋\n正文", encoding="utf-8")

    result = import_novel_txt(path)

    assert result.volumes[0].title == "第二卷"
    assert result.volumes[0].volume_number == 2
    assert result.volumes[0].chapters[0].title == "序章 平凡无奇的初恋"


@pytest.mark.parametrize(
    ("heading", "volume_title", "volume_number", "chapter_title"),
    [
        ("第1卷 第一章 某某某", "第1卷", 1, "第一章 某某某"),
        ("卷一 序章 某某某", "卷一", 1, "序章 某某某"),
        ("下卷 终章 某某某", "下卷", 2, "终章 某某某"),
        ("第一卷 第01章 某某某", "第一卷", 1, "第01章 某某某"),
    ],
)
def test_import_novel_txt_supports_wenku8_volume_chapter_heading_variants(
    tmp_path: Path,
    heading: str,
    volume_title: str,
    volume_number: int,
    chapter_title: str,
) -> None:
    path = tmp_path / "novel.txt"
    path.write_text(f"{heading}\n正文", encoding="utf-8")

    result = import_novel_txt(path)

    assert result.volumes[0].title == volume_title
    assert result.volumes[0].volume_number == volume_number
    assert result.volumes[0].chapters[0].title == chapter_title


def test_import_novel_txt_removes_source_notes_from_chapter_opening(tmp_path: Path) -> None:
    path = tmp_path / "novel.txt"
    path.write_text(
        "\n".join(
            [
                "上卷 序章 某某某",
                "台版 转自 轻之国度",
                "天使动漫录入",
                "图源：Aircer",
                "扫图：凑·凯特流",
                "录入：kid",
                "修图：不会修图的kid",
                "真正的正文",
            ]
        ),
        encoding="utf-8",
    )

    result = import_novel_txt(path)
    chapter = result.volumes[0].chapters[0]

    assert result.volumes[0].title == "上卷"
    assert result.volumes[0].volume_number == 1
    assert chapter.content == "真正的正文"
    assert "图源：Aircer" in chapter.source_notes
    assert "录入：kid" in chapter.source_notes


def test_import_novel_txt_does_not_treat_body_text_containing_chapter_word_as_heading(tmp_path: Path) -> None:
    path = tmp_path / "novel.txt"
    path.write_text(
        "\n".join(
            [
                "第一卷 序章 青春的后悔",
                "这只是普通正文里的第一章这几个字，不是标题。",
                "仍然属于序章。",
            ]
        ),
        encoding="utf-8",
    )

    result = import_novel_txt(path)

    assert result.chapter_count == 1
    assert "普通正文里的第一章" in result.volumes[0].chapters[0].content


def test_import_novel_txt_does_not_use_numeric_filename_as_title(tmp_path: Path) -> None:
    path = tmp_path / "131216.txt"
    path.write_text("第一章\n只有正文，没有标题", encoding="utf-8")

    result = import_novel_txt(path)

    assert result.source_file_id == "131216"
    assert result.title_guess == ""
    assert result.chapter_count == 1
    assert "未能从正文推测标题。" in result.warnings


def test_import_novel_txt_reads_utf8_file_with_class_wrapper(tmp_path: Path) -> None:
    path = tmp_path / "novel.txt"
    path.write_text("书名：测试小说\n作者：作者名\n第一章\n内容", encoding="utf-8")

    result = NovelTxtImporter().import_file(path)

    assert result.source_file_id is None
    assert result.encoding == "utf-8-sig"
    assert result.title_guess == "测试小说"
    assert result.author_guess == "作者名"
    assert result.chapter_count == 1


def test_import_novel_txt_keeps_plain_text_as_fallback_chapter(tmp_path: Path) -> None:
    path = tmp_path / "plain.txt"
    path.write_text("没有章节标题的全文", encoding="utf-8")

    result = import_novel_txt(path)

    assert result.chapter_count == 1
    assert result.volumes[0].chapters[0].title == "正文"
    assert result.volumes[0].chapters[0].content == "没有章节标题的全文"


def test_import_novel_txt_rejects_non_txt_file(tmp_path: Path) -> None:
    path = tmp_path / "novel.md"
    path.write_text("书名：测试", encoding="utf-8")

    with pytest.raises(ImporterError):
        import_novel_txt(path)
