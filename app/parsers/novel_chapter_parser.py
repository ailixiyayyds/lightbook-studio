from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class NovelChapter:
    title: str
    content: str
    order_index: int


@dataclass(frozen=True)
class NovelVolume:
    title: str
    volume_number: int | None
    chapters: list[NovelChapter] = field(default_factory=list)


@dataclass(frozen=True)
class NovelParseResult:
    title_guess: str
    author_guess: str
    volumes: list[NovelVolume]
    warnings: list[str] = field(default_factory=list)


_NUMBER_TEXT = r"0*[0-9０-９]+|[零〇一二三四五六七八九十百千万两]+"
_SPECIAL_CHAPTER_TITLES = r"序章|楔子|前言|终章|后记|插图|幕间|间章"

_CHAPTER_RE = re.compile(
    rf"^(?:"
    rf"(?:{_SPECIAL_CHAPTER_TITLES})(?:\s+.+)?"
    rf"|第\s*(?:{_NUMBER_TEXT})\s*[章話话](?:\s+.+)?"
    rf"|chapter\s+0*\d+(?:\s+.+)?"
    rf")$",
    re.IGNORECASE,
)
_VOLUME_RE = re.compile(
    rf"^(?:"
    rf"第\s*(?P<di_number>{_NUMBER_TEXT})\s*卷"
    rf"|卷\s*(?P<juan_number>{_NUMBER_TEXT})"
    rf"|(?P<part>[上下])卷"
    rf"|短篇集"
    rf"|番外篇"
    rf")$",
    re.IGNORECASE,
)
_TITLE_RE = re.compile(
    r"^\s*(?:书名|書名|作品名|小说名称|小說名稱|小说名|小說名|标题|標題)\s*[:：]\s*(?P<value>.+?)\s*$"
)
_AUTHOR_RE = re.compile(r"^\s*(?:作者|作\s*者)\s*[:：]\s*(?P<value>.+?)\s*$")
_ANGLE_TITLE_RE = re.compile(r"^\s*<(?P<value>[^<>]{1,120})>\s*$")


def parse_novel_text(text: str) -> NovelParseResult:
    normalized = _normalize_newlines(text)
    title_guess, author_guess = _guess_metadata(normalized)

    volumes: list[NovelVolume] = []
    current_volume_title = ""
    current_volume_number: int | None = None
    current_chapters: list[NovelChapter] = []
    current_chapter_title: str | None = None
    current_chapter_lines: list[str] = []
    order_index = 1
    saw_chapter_heading = False
    saw_volume_heading = False

    def flush_chapter() -> None:
        nonlocal current_chapter_title, current_chapter_lines, order_index
        content = "\n".join(current_chapter_lines).strip()
        if current_chapter_title is None and not content:
            current_chapter_lines = []
            return
        current_chapters.append(
            NovelChapter(
                title=current_chapter_title or "正文",
                content=content,
                order_index=order_index,
            )
        )
        order_index += 1
        current_chapter_title = None
        current_chapter_lines = []

    def flush_volume() -> None:
        nonlocal current_volume_title, current_volume_number, current_chapters
        if current_volume_title or current_chapters:
            volumes.append(
                NovelVolume(
                    title=current_volume_title,
                    volume_number=current_volume_number,
                    chapters=current_chapters,
                )
            )
        current_volume_title = ""
        current_volume_number = None
        current_chapters = []

    for line in normalized.split("\n"):
        stripped = line.strip()
        volume_info = _parse_volume_heading(stripped)
        if volume_info is not None:
            saw_volume_heading = True
            flush_chapter()
            flush_volume()
            current_volume_title = volume_info[0]
            current_volume_number = volume_info[1]
            continue

        if _is_chapter_heading(stripped):
            saw_chapter_heading = True
            flush_chapter()
            current_chapter_title = stripped
            continue

        current_chapter_lines.append(line)

    flush_chapter()
    flush_volume()

    if not saw_chapter_heading:
        fallback_content = normalized.strip()
        if volumes:
            volumes = [
                NovelVolume(
                    title=volume.title,
                    volume_number=volume.volume_number,
                    chapters=volume.chapters
                    or [
                        NovelChapter(
                            title="正文",
                            content=fallback_content,
                            order_index=1,
                        )
                    ],
                )
                for volume in volumes
            ]
        else:
            volumes = [
                NovelVolume(
                    title="",
                    volume_number=None,
                    chapters=[
                        NovelChapter(
                            title="正文",
                            content=fallback_content,
                            order_index=1,
                        )
                    ],
                )
            ]

    if not saw_volume_heading:
        volumes = [
            NovelVolume(
                title="",
                volume_number=None,
                chapters=[chapter for volume in volumes for chapter in volume.chapters],
            )
        ]

    return NovelParseResult(
        title_guess=title_guess,
        author_guess=author_guess,
        volumes=volumes,
        warnings=[],
    )


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _parse_volume_heading(stripped: str) -> tuple[str, int | None] | None:
    if not _is_title_length_ok(stripped):
        return None
    match = _VOLUME_RE.fullmatch(stripped)
    if match is None:
        return None
    number_text = match.group("di_number") or match.group("juan_number")
    if number_text:
        volume_number = _parse_number(number_text)
    elif match.group("part") == "上":
        volume_number = 1
    elif match.group("part") == "下":
        volume_number = 2
    else:
        volume_number = None
    return stripped, volume_number


def _is_chapter_heading(stripped: str) -> bool:
    if not _is_title_length_ok(stripped):
        return False
    return _CHAPTER_RE.fullmatch(stripped) is not None


def _is_title_length_ok(value: str) -> bool:
    if not value:
        return False
    compact = re.sub(r"\s+", "", value)
    return len(compact) <= 60


def _guess_metadata(text: str) -> tuple[str, str]:
    title_guess = ""
    author_guess = ""
    for line in text.split("\n")[:80]:
        if not title_guess:
            angle_match = _ANGLE_TITLE_RE.match(line)
            if angle_match:
                title_guess = angle_match.group("value").strip()
            else:
                title_match = _TITLE_RE.match(line)
                if title_match:
                    title_guess = title_match.group("value").strip()
        if not author_guess:
            author_match = _AUTHOR_RE.match(line)
            if author_match:
                author_guess = author_match.group("value").strip()
        if title_guess and author_guess:
            break
    return title_guess, author_guess


def _parse_number(value: str) -> int | None:
    normalized = value.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    normalized = normalized.lstrip("0") or "0"
    if normalized.isdigit():
        return int(normalized)
    return _parse_chinese_number(normalized)


def _parse_chinese_number(value: str) -> int | None:
    digit_map = {
        "零": 0,
        "〇": 0,
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
    }
    unit_map = {"十": 10, "百": 100, "千": 1000, "万": 10000}
    total = 0
    section = 0
    number = 0
    for char in value:
        if char in digit_map:
            number = digit_map[char]
        elif char in unit_map:
            unit = unit_map[char]
            if unit == 10000:
                total += (section + number) * unit
                section = 0
            else:
                section += (number or 1) * unit
            number = 0
        else:
            return None
    return total + section + number
