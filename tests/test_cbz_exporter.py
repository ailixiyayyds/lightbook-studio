from pathlib import Path
from zipfile import ZipFile

from PIL import Image

from app.core.models import ComicMetadata
from app.exporters.cbz_exporter import export_cbz
from app.importers.image_folder_importer import import_image_folder


def test_export_cbz_writes_comicinfo_pages_and_poster(tmp_path: Path) -> None:
    input_dir = tmp_path / "Input Manga"
    input_dir.mkdir()
    _make_image(input_dir / "page1.jpg", color=(255, 0, 0))
    _make_image(input_dir / "page2.png", color=(0, 255, 0))

    import_result = import_image_folder(input_dir)
    metadata = ComicMetadata(series_title="A:B Manga", book_title="Book", volume_number=1)

    result = export_cbz(import_result, tmp_path / "out", metadata)

    assert result.cbz_path.name == "A_B Manga v01.cbz"
    assert result.poster_path.exists()
    with ZipFile(result.cbz_path) as cbz:
        assert cbz.namelist() == ["ComicInfo.xml", "0001.jpg", "0002.png"]
        assert b"<Series>A_B Manga</Series>" not in cbz.read("ComicInfo.xml")
        assert b"<Series>A:B Manga</Series>" in cbz.read("ComicInfo.xml")


def test_export_cbz_does_not_overwrite_existing_file(tmp_path: Path) -> None:
    input_dir = tmp_path / "Input Manga"
    input_dir.mkdir()
    _make_image(input_dir / "page1.jpg")

    import_result = import_image_folder(input_dir)
    metadata = ComicMetadata(series_title="Series", book_title="Book", volume_number=1)

    first = export_cbz(import_result, tmp_path / "out", metadata)
    second = export_cbz(import_result, tmp_path / "out", metadata)

    assert first.cbz_path.name == "Series v01.cbz"
    assert second.cbz_path.name == "Series v01 (1).cbz"


def _make_image(path: Path, color: tuple[int, int, int] = (255, 0, 0)) -> None:
    Image.new("RGB", (12, 16), color=color).save(path)
