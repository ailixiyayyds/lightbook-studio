from __future__ import annotations

import pytest

from app.utils.wenku8_filename import parse_wenku8_txt_filename


@pytest.mark.parametrize(
    ("filename", "source_file_id", "encoding_hint"),
    [
        ("3159 gbk.txt", "3159", "gbk"),
        ("139089 utf8.txt", "139089", "utf8"),
        ("131216.txt", "131216", None),
        ("无职转生 第一卷.txt", None, None),
    ],
)
def test_parse_wenku8_txt_filename(
    filename: str,
    source_file_id: str | None,
    encoding_hint: str | None,
) -> None:
    info = parse_wenku8_txt_filename(filename)

    assert info.source_file_id == source_file_id
    assert info.encoding_hint == encoding_hint
    assert info.original_name == filename
