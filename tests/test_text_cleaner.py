from __future__ import annotations

from app.utils.text_cleaner import clean_novel_text, remove_ad_lines


def test_clean_novel_text_normalizes_newlines_and_trims_trailing_spaces() -> None:
    text = "第一行  \r\n第二行\t\r第三行  "

    assert clean_novel_text(text) == "第一行\n第二行\n第三行"


def test_clean_novel_text_compresses_three_or_more_blank_lines_to_two() -> None:
    text = "第一段\n\n\n\n第二段\n\n第三段"

    assert clean_novel_text(text) == "第一段\n\n第二段\n\n第三段"


def test_clean_novel_text_strips_outer_whitespace_but_keeps_paragraphs() -> None:
    text = "\n\n  第一段\n\n第二段  \n\n"

    assert clean_novel_text(text) == "  第一段\n\n第二段"


def test_remove_ad_lines_deletes_only_obvious_ad_lines() -> None:
    text = "\n".join(
        [
            "序章",
            "本电子书由轻小说文库整理",
            "这是正文里的轻小说文库四个字，不应删除。",
            "更多小说请访问 www.wenku8.net",
            "结束",
        ]
    )

    assert remove_ad_lines(text) == "\n".join(
        [
            "序章",
            "这是正文里的轻小说文库四个字，不应删除。",
            "结束",
        ]
    )


def test_clean_novel_text_removes_obvious_ad_lines() -> None:
    text = "正文\n轻小说文库 www.wenku8.net\n\n\n下一段"

    assert clean_novel_text(text) == "正文\n\n下一段"
