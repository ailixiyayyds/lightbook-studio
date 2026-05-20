from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Wenku8FilenameInfo:
    source_file_id: str | None
    encoding_hint: str | None
    original_name: str


_WENKU8_FILENAME_RE = re.compile(
    r"^(?P<source_file_id>\d+)(?:\s+(?P<encoding_hint>gbk|gb18030|utf8|utf-8))?$",
    re.IGNORECASE,
)


def parse_wenku8_txt_filename(filename: str) -> Wenku8FilenameInfo:
    original_name = Path(filename).name
    stem = Path(original_name).stem.strip()
    match = _WENKU8_FILENAME_RE.fullmatch(stem)
    if match is None:
        return Wenku8FilenameInfo(
            source_file_id=None,
            encoding_hint=None,
            original_name=original_name,
        )

    encoding_hint = match.group("encoding_hint")
    return Wenku8FilenameInfo(
        source_file_id=match.group("source_file_id"),
        encoding_hint=encoding_hint.casefold() if encoding_hint else None,
        original_name=original_name,
    )
