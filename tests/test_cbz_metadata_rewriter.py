from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

from app.core.models import ComicMetadata
from app.exporters.cbz_metadata_rewriter import rewrite_cbz_metadata


def test_rewrite_cbz_metadata_preserves_images_and_replaces_comicinfo(tmp_path: Path) -> None:
    source_path = tmp_path / "source.cbz"
    output_path = tmp_path / "rewritten.cbz"
    _write_source_cbz(source_path)
    original_bytes = source_path.read_bytes()

    result = rewrite_cbz_metadata(
        source_path,
        output_path,
        ComicMetadata(
            series_title="New Series",
            book_title="New Book",
            volume_number=2,
            author="Author",
            translator="Translator",
            summary="Summary",
            genres=["Drama"],
            tags=["new-tag", "edited"],
            language_iso="zh",
            manga_direction="rtl",
        ),
    )

    assert result.cbz_path == output_path
    assert result.warnings == ["已忽略非图片文件：notes.txt"]

    with ZipFile(output_path) as archive:
        names = archive.namelist()
        comicinfo = archive.read("ComicInfo.xml").decode("utf-8")
        assert "pages/page1.jpg" in names
        assert "pages/page2.png" in names
        assert archive.read("pages/page1.jpg") == b"page-1"
        assert archive.read("pages/page2.png") == b"page-2"
        assert "notes.txt" not in names
        assert "<Series>New Series</Series>" in comicinfo
        assert "<Tags>new-tag, edited</Tags>" in comicinfo
        assert "Old Series" not in comicinfo

    assert source_path.read_bytes() == original_bytes
    with ZipFile(source_path) as archive:
        assert archive.read("ComicInfo.xml") == _old_comicinfo_xml()


def test_rewrite_cbz_metadata_does_not_overwrite_existing_output(tmp_path: Path) -> None:
    source_path = tmp_path / "source.cbz"
    output_path = tmp_path / "rewritten.cbz"
    _write_source_cbz(source_path)
    output_path.write_bytes(b"existing")

    result = rewrite_cbz_metadata(
        source_path,
        output_path,
        ComicMetadata(series_title="Series", book_title="Book", volume_number=1),
    )

    assert result.cbz_path == tmp_path / "rewritten (1).cbz"
    assert output_path.read_bytes() == b"existing"


def test_rewrite_cbz_metadata_can_replace_cover_image(tmp_path: Path) -> None:
    source_path = tmp_path / "source.cbz"
    output_path = tmp_path / "rewritten.cbz"
    cover_path = tmp_path / "cover.webp"
    _write_source_cbz(source_path)
    cover_path.write_bytes(b"new-cover")

    result = rewrite_cbz_metadata(
        source_path,
        output_path,
        ComicMetadata(series_title="Series", book_title="Book", volume_number=1),
        cover_override_path=cover_path,
    )

    with ZipFile(result.cbz_path) as archive:
        names = archive.namelist()
        assert "pages/page1.webp" in names
        assert archive.read("pages/page1.webp") == b"new-cover"
        assert archive.read("pages/page2.png") == b"page-2"


def _write_source_cbz(path: Path) -> None:
    with ZipFile(path, "w") as archive:
        archive.writestr("ComicInfo.xml", _old_comicinfo_xml())
        archive.writestr("pages/page1.jpg", b"page-1")
        archive.writestr("pages/page2.png", b"page-2")
        archive.writestr("notes.txt", b"ignored")


def _old_comicinfo_xml() -> bytes:
    return b"""<?xml version="1.0" encoding="utf-8"?>
<ComicInfo>
  <Series>Old Series</Series>
  <Title>Old Book</Title>
  <Tags>old-tag</Tags>
</ComicInfo>
"""
