from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

import pytest

from app.core.models import ImporterError
from app.importers.cbz_importer import CbzImporter, import_cbz


def test_import_cbz_reads_image_list(tmp_path: Path) -> None:
    cbz_path = tmp_path / "Series v01.cbz"
    with ZipFile(cbz_path, "w") as archive:
        archive.writestr("page001.jpg", b"jpg")
        archive.writestr("page002.png", b"png")
        archive.writestr("page003.webp", b"webp")
        archive.writestr("page004.gif", b"gif")
        archive.writestr("notes.txt", b"ignored")

    result = CbzImporter().import_file(cbz_path)

    assert result.source_path == cbz_path
    assert result.source_type == "cbz"
    assert [page.archive_path for page in result.pages] == [
        "page001.jpg",
        "page002.png",
        "page003.webp",
        "page004.gif",
    ]
    assert [page.source_path for page in result.pages] == [cbz_path] * 4
    assert result.cover_data == b"jpg"
    assert result.cover_extension == "jpg"


def test_import_cbz_sorts_images_naturally(tmp_path: Path) -> None:
    cbz_path = tmp_path / "Series v01.cbz"
    with ZipFile(cbz_path, "w") as archive:
        archive.writestr("page10.jpg", b"10")
        archive.writestr("page2.jpg", b"2")
        archive.writestr("page1.jpg", b"1")

    result = import_cbz(cbz_path)

    assert [page.archive_path for page in result.pages] == [
        "page1.jpg",
        "page2.jpg",
        "page10.jpg",
    ]


def test_import_cbz_parses_comicinfo_xml(tmp_path: Path) -> None:
    cbz_path = tmp_path / "ignored.cbz"
    with ZipFile(cbz_path, "w") as archive:
        archive.writestr("ComicInfo.xml", _comicinfo_xml())
        archive.writestr("pages/001.jpg", b"cover")

    result = import_cbz(cbz_path)

    assert result.metadata.series_title == "Series Name"
    assert result.metadata.book_title == "Book Title"
    assert result.metadata.volume_number == 3
    assert result.metadata.author == "Writer Name"
    assert result.metadata.translator == "Group Name"
    assert result.metadata.summary == "Summary text"
    assert result.metadata.genres == ["Fantasy", "Drama"]
    assert result.metadata.tags == ["tag-a", "tag-b"]
    assert result.metadata.language_iso == "zh"
    assert result.metadata.manga_direction == "rtl"


def test_import_cbz_falls_back_to_filename_metadata(tmp_path: Path) -> None:
    cbz_path = tmp_path / "Sono Bisque Doll wa Koi wo Suru v08.cbz"
    with ZipFile(cbz_path, "w") as archive:
        archive.writestr("001.jpg", b"cover")

    result = import_cbz(cbz_path)

    assert result.metadata.series_title == "Sono Bisque Doll wa Koi wo Suru"
    assert result.metadata.book_title == "Sono Bisque Doll wa Koi wo Suru v08"
    assert result.metadata.volume_number == 8


def test_import_cbz_raises_when_no_images(tmp_path: Path) -> None:
    cbz_path = tmp_path / "empty.cbz"
    with ZipFile(cbz_path, "w") as archive:
        archive.writestr("ComicInfo.xml", _comicinfo_xml())
        archive.writestr("notes.txt", b"no images")

    with pytest.raises(ImporterError, match="没有找到"):
        import_cbz(cbz_path)


def _comicinfo_xml() -> bytes:
    return b"""<?xml version="1.0" encoding="utf-8"?>
<ComicInfo>
  <Series>Series Name</Series>
  <Title>Book Title</Title>
  <Number>3</Number>
  <Writer>Writer Name</Writer>
  <Translator>Group Name</Translator>
  <Summary>Summary text</Summary>
  <Genre>Fantasy, Drama</Genre>
  <Tags>tag-a, tag-b</Tags>
  <LanguageISO>zh</LanguageISO>
  <Manga>YesAndRightToLeft</Manga>
</ComicInfo>
"""
