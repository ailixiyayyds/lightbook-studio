from xml.etree import ElementTree as ET

from app.core.models import ComicMetadata
from app.exporters.comicinfo_writer import build_comicinfo_xml


def test_build_comicinfo_xml_contains_required_fields() -> None:
    metadata = ComicMetadata(
        series_title="Series",
        book_title="Volume One",
        volume_number=1,
        author="Author",
        translator="Group",
        summary="Summary text",
        genres=["Action", "Fantasy"],
        tags=["Tag A", "Tag B"],
        language_iso="zh",
        manga_direction="rtl",
    )

    root = ET.fromstring(build_comicinfo_xml(metadata))

    assert root.findtext("Series") == "Series"
    assert root.findtext("Title") == "Volume One"
    assert root.findtext("Number") == "1"
    assert root.findtext("Writer") == "Author"
    assert root.findtext("Translator") == "Group"
    assert root.findtext("Summary") == "Summary text"
    assert root.findtext("Genre") == "Action, Fantasy"
    assert root.findtext("Tags") == "Tag A, Tag B"
    assert root.findtext("LanguageISO") == "zh"
    assert root.findtext("Manga") == "YesAndRightToLeft"
