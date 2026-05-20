from pathlib import Path

from PIL import Image

from app.importers.image_folder_importer import import_image_folder


def test_import_image_folder_reads_supported_images_in_natural_order(tmp_path: Path) -> None:
    folder = tmp_path / "My Series"
    folder.mkdir()
    _make_image(folder / "page10.jpg")
    _make_image(folder / "page2.png")
    _make_image(folder / "page1.webp")
    (folder / "notes.txt").write_text("ignore", encoding="utf-8")

    result = import_image_folder(folder)

    assert result.source_type == "image_folder"
    assert [page.display_name for page in result.pages] == [
        "page1.webp",
        "page2.png",
        "page10.jpg",
    ]
    assert result.metadata.series_title == "My Series"
    assert result.cover_data == (folder / "page1.webp").read_bytes()


def _make_image(path: Path) -> None:
    Image.new("RGB", (10, 10), color=(1, 2, 3)).save(path)
