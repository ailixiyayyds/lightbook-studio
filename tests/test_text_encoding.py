from __future__ import annotations

from pathlib import Path

import pytest

from app.utils.text_encoding import TextDecodeError, detect_and_read_text


def test_detect_and_read_text_reads_utf8(tmp_path: Path) -> None:
    path = tmp_path / "utf8.txt"
    path.write_bytes("第一行\r\n第二行".encode("utf-8"))

    text, encoding = detect_and_read_text(path)

    assert text == "第一行\n第二行"
    assert encoding == "utf-8-sig"


def test_detect_and_read_text_reads_utf8_bom(tmp_path: Path) -> None:
    path = tmp_path / "utf8_bom.txt"
    path.write_bytes("带 BOM\r\n文本".encode("utf-8-sig"))

    text, encoding = detect_and_read_text(path)

    assert text == "带 BOM\n文本"
    assert encoding == "utf-8-sig"


def test_detect_and_read_text_reads_gbk(tmp_path: Path) -> None:
    path = tmp_path / "gbk.txt"
    path.write_bytes("轻小说文库\r\n章节".encode("gbk"))

    text, encoding = detect_and_read_text(path)

    assert text == "轻小说文库\n章节"
    assert encoding == "gb18030"


def test_detect_and_read_text_reads_gb18030(tmp_path: Path) -> None:
    path = tmp_path / "gb18030.txt"
    path.write_bytes("GB18030 字符 𠮷\r章节".encode("gb18030"))

    text, encoding = detect_and_read_text(path)

    assert text == "GB18030 字符 𠮷\n章节"
    assert encoding == "gb18030"


def test_detect_and_read_text_raises_clear_error_when_decode_fails(tmp_path: Path) -> None:
    path = tmp_path / "bad.txt"
    path.write_bytes(b"\xff\xff\xff\xff\xff")

    with pytest.raises(TextDecodeError) as exc_info:
        detect_and_read_text(path)

    assert str(path) in str(exc_info.value)
