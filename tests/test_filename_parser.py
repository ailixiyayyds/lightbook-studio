from __future__ import annotations

import pytest

from app.utils.filename_parser import parse_comic_filename


@pytest.mark.parametrize(
    ("name", "series_title", "book_title", "volume_number"),
    [
        ("葬送的芙莉莲 第01卷.epub", "葬送的芙莉莲", "葬送的芙莉莲 第01卷", 1),
        ("葬送的芙莉莲 第1卷.epub", "葬送的芙莉莲", "葬送的芙莉莲 第1卷", 1),
        ("葬送的芙莉莲 卷02.epub", "葬送的芙莉莲", "葬送的芙莉莲 卷02", 2),
        ("葬送的芙莉莲 Vol.03.epub", "葬送的芙莉莲", "葬送的芙莉莲 Vol.03", 3),
        ("葬送的芙莉莲 vol 4.epub", "葬送的芙莉莲", "葬送的芙莉莲 vol 4", 4),
        ("葬送的芙莉莲 Volume 5.epub", "葬送的芙莉莲", "葬送的芙莉莲 Volume 5", 5),
        ("葬送的芙莉莲 v06.epub", "葬送的芙莉莲", "葬送的芙莉莲 v06", 6),
        ("[汉化] 葬送的芙莉莲 第07卷 [Kome].epub", "葬送的芙莉莲", "葬送的芙莉莲 第07卷", 7),
        (
            "Sono Bisque Doll wa Koi wo Suru v08.epub",
            "Sono Bisque Doll wa Koi wo Suru",
            "Sono Bisque Doll wa Koi wo Suru v08",
            8,
        ),
    ],
)
def test_parse_comic_filename_detects_volume(
    name: str,
    series_title: str,
    book_title: str,
    volume_number: int,
) -> None:
    parsed = parse_comic_filename(name)

    assert parsed.series_title == series_title
    assert parsed.book_title == book_title
    assert parsed.volume_number == volume_number
    assert parsed.is_chapter is False
    assert parsed.chapter_number is None
    assert parsed.warnings == []


def test_parse_comic_filename_detects_chapter() -> None:
    parsed = parse_comic_filename("漫画名 第12话.epub")

    assert parsed.series_title == "漫画名"
    assert parsed.book_title == "漫画名 第12话"
    assert parsed.volume_number is None
    assert parsed.is_chapter is True
    assert parsed.chapter_number == 12
    assert parsed.warnings == []
