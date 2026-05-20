from __future__ import annotations

from pathlib import Path

from app.services.output_planner import plan_comic_output, plan_novel_output


def test_plan_comic_output_uses_default_volume_template(tmp_path: Path) -> None:
    planned = plan_comic_output(
        tmp_path,
        "A:B Manga",
        "Book Title",
        1,
    )

    assert planned.series_dir == tmp_path / "Manga" / "A_B Manga"
    assert planned.cbz_path == tmp_path / "Manga" / "A_B Manga" / "A_B Manga v01.cbz"
    assert planned.poster_path == tmp_path / "Manga" / "A_B Manga" / "poster.jpg"


def test_plan_comic_output_uses_book_title_when_volume_is_missing(tmp_path: Path) -> None:
    planned = plan_comic_output(
        tmp_path,
        "Series",
        'Chapter 12: A/B?C"',
        None,
    )

    assert planned.series_dir == tmp_path / "Manga" / "Series"
    assert planned.cbz_path == tmp_path / "Manga" / "Series" / "Chapter 12_ A_B_C_.cbz"
    assert planned.poster_path == tmp_path / "Manga" / "Series" / "poster.jpg"


def test_plan_comic_output_avoids_overwriting_existing_cbz(tmp_path: Path) -> None:
    series_dir = tmp_path / "Manga" / "Series"
    series_dir.mkdir(parents=True)
    (series_dir / "Series v02.cbz").write_bytes(b"existing")
    (series_dir / "Series v02 (1).cbz").write_bytes(b"existing")

    planned = plan_comic_output(
        tmp_path,
        "Series",
        "Book",
        2,
    )

    assert planned.cbz_path == series_dir / "Series v02 (2).cbz"


def test_plan_comic_output_sanitizes_series_and_book_fallbacks(tmp_path: Path) -> None:
    planned = plan_comic_output(
        tmp_path,
        r'Bad\Series<Name>',
        "",
        None,
    )

    assert planned.series_dir == tmp_path / "Manga" / "Bad_Series_Name_"
    assert planned.cbz_path == tmp_path / "Manga" / "Bad_Series_Name_" / "Untitled.cbz"


def test_plan_novel_output_uses_volume_template(tmp_path: Path) -> None:
    planned = plan_novel_output(
        tmp_path,
        "Novel:Series",
        "第一卷",
        1,
    )

    assert planned.series_dir == tmp_path / "Novel" / "Novel_Series"
    assert planned.epub_path == tmp_path / "Novel" / "Novel_Series" / "Novel_Series v01.epub"


def test_plan_novel_output_uses_book_title_when_volume_is_missing(tmp_path: Path) -> None:
    planned = plan_novel_output(
        tmp_path,
        "Novel Series",
        'Side:Story?',
        None,
    )

    assert planned.series_dir == tmp_path / "Novel" / "Novel Series"
    assert planned.epub_path == tmp_path / "Novel" / "Novel Series" / "Side_Story_.epub"


def test_plan_novel_output_avoids_overwriting_existing_epub(tmp_path: Path) -> None:
    series_dir = tmp_path / "Novel" / "Novel Series"
    series_dir.mkdir(parents=True)
    (series_dir / "Novel Series v02.epub").write_bytes(b"existing")

    planned = plan_novel_output(
        tmp_path,
        "Novel Series",
        "Second",
        2,
    )

    assert planned.epub_path == series_dir / "Novel Series v02 (1).epub"
