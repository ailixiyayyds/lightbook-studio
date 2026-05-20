from __future__ import annotations

import re

_THREE_OR_MORE_BLANK_LINES_RE = re.compile(r"\n[ \t]*\n[ \t]*\n+")

_OBVIOUS_AD_PATTERNS = (
    re.compile(r"^\s*本电子书由.*?(?:整理|制作|提供)\s*$"),
    re.compile(r"^\s*更多.*?(?:小说|电子书).*?(?:请访问|访问)\s*\S+\s*$"),
    re.compile(r"^\s*★☆★☆★☆轻小说文库\(\s*www\.wenku8\.com\s*\)☆★☆★☆★\s*$", re.IGNORECASE),
    re.compile(r"^\s*(?:轻小说文库|wenku8).*?(?:www\.wenku8|wenku8\.net).*$", re.IGNORECASE),
)


def clean_novel_text(text: str) -> str:
    normalized = _normalize_newlines(text)
    without_ads = remove_ad_lines(normalized)
    stripped_lines = "\n".join(line.rstrip(" \t") for line in without_ads.split("\n"))
    compressed = _compress_blank_lines(stripped_lines)
    return _strip_outer_blank_lines(compressed)


def remove_ad_lines(text: str) -> str:
    lines = text.split("\n")
    kept_lines = [line for line in lines if not _is_obvious_ad_line(line)]
    return "\n".join(kept_lines)


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _compress_blank_lines(text: str) -> str:
    previous = None
    current = text
    while previous != current:
        previous = current
        current = _THREE_OR_MORE_BLANK_LINES_RE.sub("\n\n", current)
    return current


def _strip_outer_blank_lines(text: str) -> str:
    lines = text.split("\n")
    while lines and not lines[0].strip(" \t"):
        lines.pop(0)
    while lines and not lines[-1].strip(" \t"):
        lines.pop()
    return "\n".join(lines)


def _is_obvious_ad_line(line: str) -> bool:
    return any(pattern.search(line) for pattern in _OBVIOUS_AD_PATTERNS)
