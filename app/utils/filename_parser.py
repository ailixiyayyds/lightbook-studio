from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ParsedFilename:
    series_title: str
    book_title: str
    volume_number: int | None
    is_chapter: bool
    chapter_number: int | None
    warnings: list[str] = field(default_factory=list)


_KNOWN_EXTENSIONS_RE = re.compile(
    r"\.(?:epub|cbz|zip|rar|7z|jpg|jpeg|png|webp)$",
    re.IGNORECASE,
)
_BRACKET_RE = re.compile(r"\[([^\[\]]+)\]|【([^】]+)】|［([^］]+)］")
_WHITESPACE_RE = re.compile(r"\s+")
_COMMON_BRACKET_TAG_RE = re.compile(
    r"^(?:"
    r"\d+"
    r"|kome"
    r"|汉化|漢化|汉化组|漢化組|翻译|翻譯"
    r"|简体|簡體|繁体|繁體|简中|繁中"
    r"|中文|chinese|digital|scan|scans"
    r")$",
    re.IGNORECASE,
)

_CHAPTER_PATTERNS = [
    re.compile(r"第\s*0*(?P<number>\d+)\s*[话話]", re.IGNORECASE),
]

_VOLUME_PATTERNS = [
    re.compile(r"第\s*0*(?P<number>\d+)\s*[卷冊册]", re.IGNORECASE),
    re.compile(r"[卷冊册]\s*0*(?P<number>\d+)", re.IGNORECASE),
    re.compile(r"\bvolume\s*0*(?P<number>\d+)\b", re.IGNORECASE),
    re.compile(r"\bvol\.?\s*0*(?P<number>\d+)\b", re.IGNORECASE),
    re.compile(r"\bv\s*0*(?P<number>\d+)\b", re.IGNORECASE),
]


def parse_comic_filename(name: str) -> ParsedFilename:
    warnings: list[str] = []
    cleaned_name = _clean_filename(name)

    if not cleaned_name:
        return ParsedFilename(
            series_title="",
            book_title="",
            volume_number=None,
            is_chapter=False,
            chapter_number=None,
            warnings=["文件名为空，无法解析。"],
        )

    chapter_match = _find_first_match(cleaned_name, _CHAPTER_PATTERNS)
    if chapter_match is not None:
        series_title = _clean_series_title(cleaned_name[: chapter_match.start()])
        if not series_title:
            warnings.append("未能从话号前识别作品名。")
        return ParsedFilename(
            series_title=series_title,
            book_title=cleaned_name,
            volume_number=None,
            is_chapter=True,
            chapter_number=_parse_number(chapter_match),
            warnings=warnings,
        )

    volume_match = _find_first_match(cleaned_name, _VOLUME_PATTERNS)
    if volume_match is not None:
        series_title = _clean_series_title(cleaned_name[: volume_match.start()])
        if not series_title:
            warnings.append("未能从卷号前识别作品名。")
        return ParsedFilename(
            series_title=series_title,
            book_title=cleaned_name,
            volume_number=_parse_number(volume_match),
            is_chapter=False,
            chapter_number=None,
            warnings=warnings,
        )

    warnings.append("未识别到卷号或话号。")
    return ParsedFilename(
        series_title=cleaned_name,
        book_title=cleaned_name,
        volume_number=None,
        is_chapter=False,
        chapter_number=None,
        warnings=warnings,
    )


def _clean_filename(name: str) -> str:
    file_name = name.replace("\\", "/").rstrip("/").split("/")[-1]
    without_extension = _KNOWN_EXTENSIONS_RE.sub("", file_name)
    without_tags = _BRACKET_RE.sub(_remove_common_bracket_tag, without_extension)
    return _normalize_spaces(without_tags)


def _remove_common_bracket_tag(match: re.Match[str]) -> str:
    content = next(group for group in match.groups() if group is not None)
    normalized = _normalize_spaces(content)
    if _COMMON_BRACKET_TAG_RE.fullmatch(normalized):
        return " "
    return match.group(0)


def _find_first_match(
    value: str,
    patterns: list[re.Pattern[str]],
) -> re.Match[str] | None:
    matches: list[re.Match[str]] = []
    for pattern in patterns:
        matches.extend(pattern.finditer(value))
    if not matches:
        return None
    return sorted(matches, key=lambda match: match.start())[0]


def _parse_number(match: re.Match[str]) -> int:
    return int(match.group("number"))


def _clean_series_title(value: str) -> str:
    return _normalize_spaces(value).strip(" -_~:：|")


def _normalize_spaces(value: str) -> str:
    return _WHITESPACE_RE.sub(" ", value).strip()
