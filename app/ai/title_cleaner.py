from __future__ import annotations

import re
from pathlib import Path


_BRACKET_RE = re.compile(r"[\[\【\(\（]([^\]\】\)\）]{1,60})[\]\】\)\）]")
_EXTENSIONS = {".epub", ".cbz", ".zip", ".txt"}
_VOLUME_PATTERNS = [
    re.compile(r"\s*第\s*\d+\s*卷\s*$", re.IGNORECASE),
    re.compile(r"\s*卷\s*\d+\s*$", re.IGNORECASE),
    re.compile(r"\s*v(?:ol(?:ume)?\.?)?\s*\d+\s*$", re.IGNORECASE),
]


def clean_release_title(raw: str) -> str:
    text = Path(str(raw).strip()).name
    suffix = Path(text).suffix
    if suffix.casefold() in _EXTENSIONS:
        text = text[: -len(suffix)]

    text = _strip_known_noise_brackets(text)
    text = _prefer_title_bracket_when_rest_is_volume(text)
    text = _strip_remaining_noise_brackets(text)
    text = _strip_volume_suffix(text)
    return _normalize_spaces(text)


def infer_book_title(volume_number: int | None, raw_book_title: str) -> str:
    if volume_number is not None:
        return f"第 {int(volume_number):02d} 卷"
    cleaned = clean_release_title(raw_book_title)
    return cleaned


def _strip_known_noise_brackets(text: str) -> str:
    result = str(text)
    while True:
        match = _BRACKET_RE.search(result)
        if match is None:
            return result
        content = match.group(1).strip()
        if not _is_noise_marker(content):
            return result
        result = (result[: match.start()] + result[match.end() :]).strip()


def _prefer_title_bracket_when_rest_is_volume(text: str) -> str:
    match = _BRACKET_RE.search(text)
    if match is None:
        return text
    content = match.group(1).strip()
    rest = (text[: match.start()] + text[match.end() :]).strip()
    if content and rest and not _strip_volume_suffix(rest):
        return content
    return text


def _strip_remaining_noise_brackets(text: str) -> str:
    result = str(text)
    while True:
        match = _BRACKET_RE.search(result)
        if match is None:
            return result
        content = match.group(1).strip()
        rest = (result[: match.start()] + result[match.end() :]).strip()
        if rest and (_is_noise_marker(content) or _looks_like_release_marker(content)):
            result = rest
        else:
            return result


def _strip_volume_suffix(text: str) -> str:
    result = str(text)
    changed = True
    while changed:
        changed = False
        for pattern in _VOLUME_PATTERNS:
            new_value = pattern.sub("", result)
            if new_value != result:
                result = new_value
                changed = True
    return _normalize_spaces(result)


def _is_noise_marker(content: str) -> bool:
    lowered = content.casefold()
    if lowered in {"kome", "kmoe", "dl"}:
        return True
    if content.isdigit():
        return True
    return any(
        marker in content
        for marker in ("汉化", "漢化", "自购", "自購", "扫图", "掃圖", "翻译", "翻譯", "发布", "發布")
    )


def _looks_like_release_marker(content: str) -> bool:
    return len(content) <= 12 and bool(re.search(r"\d|ver|版|组|組|raw|scan", content, re.IGNORECASE))


def _normalize_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" _-　")
