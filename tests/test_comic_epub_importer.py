from pathlib import Path
from zipfile import ZipFile

from PIL import Image

from app.importers.comic_epub_importer import import_comic_epub


def test_import_comic_epub_uses_spine_order_and_metadata(tmp_path: Path) -> None:
    epub_path = tmp_path / "comic.epub"
    images = {
        "OEBPS/images/page10.jpg": _image_bytes("JPEG"),
        "OEBPS/images/page2.png": _image_bytes("PNG"),
    }
    with ZipFile(epub_path, "w") as epub:
        _write_container(epub)
        epub.writestr(
            "OEBPS/content.opf",
            """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" xmlns:dc="http://purl.org/dc/elements/1.1/" version="3.0">
  <metadata>
    <dc:title>EPUB Title</dc:title>
    <dc:creator>EPUB Author</dc:creator>
    <dc:language>zh</dc:language>
    <dc:description>EPUB Summary</dc:description>
    <dc:subject>Drama</dc:subject>
  </metadata>
  <manifest>
    <item id="p1" href="p1.xhtml" media-type="application/xhtml+xml"/>
    <item id="p2" href="p2.xhtml" media-type="application/xhtml+xml"/>
    <item id="img10" href="images/page10.jpg" media-type="image/jpeg"/>
    <item id="img2" href="images/page2.png" media-type="image/png"/>
  </manifest>
  <spine>
    <itemref idref="p1"/>
    <itemref idref="p2"/>
  </spine>
</package>
""",
        )
        epub.writestr("OEBPS/p1.xhtml", '<html><body><img src="images/page10.jpg"/></body></html>')
        epub.writestr("OEBPS/p2.xhtml", '<html><body><img src="images/page2.png"/></body></html>')
        for name, data in images.items():
            epub.writestr(name, data)

    result = import_comic_epub(epub_path)

    assert [page.archive_path for page in result.pages] == [
        "OEBPS/images/page10.jpg",
        "OEBPS/images/page2.png",
    ]
    assert result.metadata.series_title == "EPUB Title"
    assert result.metadata.author == "EPUB Author"
    assert result.metadata.summary == "EPUB Summary"
    assert result.metadata.genres == ["Drama"]
    assert result.warnings == []


def test_import_comic_epub_falls_back_to_natural_image_order(tmp_path: Path) -> None:
    epub_path = tmp_path / "fallback.epub"
    with ZipFile(epub_path, "w") as epub:
        _write_container(epub)
        epub.writestr(
            "OEBPS/content.opf",
            """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" xmlns:dc="http://purl.org/dc/elements/1.1/" version="3.0">
  <metadata><dc:title>Fallback</dc:title></metadata>
  <manifest>
    <item id="img10" href="images/page10.jpg" media-type="image/jpeg"/>
    <item id="img2" href="images/page2.jpg" media-type="image/jpeg"/>
  </manifest>
</package>
""",
        )
        epub.writestr("OEBPS/images/page10.jpg", _image_bytes("JPEG"))
        epub.writestr("OEBPS/images/page2.jpg", _image_bytes("JPEG"))

    result = import_comic_epub(epub_path)

    assert [page.archive_path for page in result.pages] == [
        "OEBPS/images/page2.jpg",
        "OEBPS/images/page10.jpg",
    ]
    assert any("回退" in warning for warning in result.warnings)


def _write_container(epub: ZipFile) -> None:
    epub.writestr(
        "META-INF/container.xml",
        """<?xml version="1.0" encoding="utf-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
""",
    )


def _image_bytes(image_format: str) -> bytes:
    from io import BytesIO

    stream = BytesIO()
    Image.new("RGB", (10, 10), color=(10, 20, 30)).save(stream, format=image_format)
    return stream.getvalue()
