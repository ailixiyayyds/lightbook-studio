from __future__ import annotations

from pathlib import Path


ENCODING_CANDIDATES = (
    "utf-8-sig",
    "utf-8",
    "gb18030",
    "gbk",
    "utf-16le",
    "utf-16",
)


class TextDecodeError(Exception):
    """Raised when a text file cannot be decoded with supported encodings."""


def detect_and_read_text(path: Path) -> tuple[str, str]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise TextDecodeError(f"无法读取文本文件 {path}: {exc}") from exc

    errors: list[str] = []
    for encoding in ENCODING_CANDIDATES:
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError as exc:
            errors.append(f"{encoding}: {exc}")
            continue
        return _normalize_newlines(text), encoding

    details = "; ".join(errors)
    raise TextDecodeError(f"无法解码文本文件 {path}。尝试的编码：{details}")


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")
