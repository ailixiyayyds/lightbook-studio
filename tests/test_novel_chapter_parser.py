from __future__ import annotations

from app.parsers.novel_chapter_parser import parse_novel_text


def test_parse_novel_text_detects_arabic_chapter_number() -> None:
    result = parse_novel_text("第1章\n内容")

    chapter = result.volumes[0].chapters[0]
    assert result.volumes[0].title == ""
    assert chapter.title == "第1章"
    assert chapter.content == "内容"
    assert chapter.order_index == 1


def test_parse_novel_text_detects_chinese_chapter_number() -> None:
    result = parse_novel_text("第一章\n内容")

    assert result.volumes[0].chapters[0].title == "第一章"
    assert result.volumes[0].chapters[0].content == "内容"


def test_parse_novel_text_detects_prologue_and_afterword() -> None:
    result = parse_novel_text("序章\n开始\n后记\n结束")

    assert [chapter.title for chapter in result.volumes[0].chapters] == ["序章", "后记"]
    assert [chapter.content for chapter in result.volumes[0].chapters] == ["开始", "结束"]


def test_parse_novel_text_detects_multiple_chapters() -> None:
    result = parse_novel_text("第01章\n一\n第十二章\n二\nCHAPTER 01\n三")

    assert [chapter.title for chapter in result.volumes[0].chapters] == [
        "第01章",
        "第十二章",
        "CHAPTER 01",
    ]
    assert [chapter.order_index for chapter in result.volumes[0].chapters] == [1, 2, 3]


def test_parse_novel_text_detects_multiple_volumes() -> None:
    result = parse_novel_text("第一卷\n第一章\n一\n下卷\n第1话\n二")

    assert len(result.volumes) == 2
    assert result.volumes[0].title == "第一卷"
    assert result.volumes[0].volume_number == 1
    assert result.volumes[0].chapters[0].title == "第一章"
    assert result.volumes[1].title == "下卷"
    assert result.volumes[1].volume_number == 2
    assert result.volumes[1].chapters[0].title == "第1话"


def test_parse_novel_text_creates_default_chapter_when_no_heading() -> None:
    result = parse_novel_text("没有章节标题的正文\n第二行")

    assert len(result.volumes) == 1
    assert result.volumes[0].title == ""
    assert result.volumes[0].volume_number is None
    assert len(result.volumes[0].chapters) == 1
    assert result.volumes[0].chapters[0].title == "正文"
    assert result.volumes[0].chapters[0].content == "没有章节标题的正文\n第二行"


def test_parse_novel_text_does_not_misread_chapter_word_in_body() -> None:
    text = "序章\n这是正文里的第一章几个字，不是标题。\n仍然属于序章。"

    result = parse_novel_text(text)

    assert len(result.volumes[0].chapters) == 1
    assert result.volumes[0].chapters[0].title == "序章"
    assert "正文里的第一章" in result.volumes[0].chapters[0].content


def test_parse_novel_text_supports_volume_title_variants() -> None:
    result = parse_novel_text("卷01\n幕间\n内容\n短篇集\n插图\n图")

    assert result.volumes[0].title == "卷01"
    assert result.volumes[0].volume_number == 1
    assert result.volumes[0].chapters[0].title == "幕间"
    assert result.volumes[1].title == "短篇集"
    assert result.volumes[1].volume_number is None
    assert result.volumes[1].chapters[0].title == "插图"
