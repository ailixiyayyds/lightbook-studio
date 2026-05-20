from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class NovelChapter:
    title: str
    content: str
    index: int
    source_notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class NovelVolume:
    title: str
    volume_number: int | None = None
    chapters: list[NovelChapter] = field(default_factory=list)


_NUMBER_TEXT = r"0*[0-9０-９]+|[零〇一二三四五六七八九十百千万两]+"
_VOLUME_AT_START_RE = re.compile(
    rf"^\s*(?P<title>第\s*(?P<number>{_NUMBER_TEXT})\s*卷|卷\s*(?P<alt_number>{_NUMBER_TEXT})|(?P<part>[上中下])卷)"
    rf"(?:\s+(?P<rest>.+))?\s*$"
)
_CHAPTER_HEADING_RE = re.compile(
    rf"^\s*(?:"
    rf"(?:序章|楔子|终章|后记|尾声)(?:\s+.+)?"
    rf"|第\s*(?:{_NUMBER_TEXT})\s*[章节話话](?:\s+.+)?"
    rf"|chapter\s+\d+(?:\s+.+)?"
    rf")\s*$",
    re.IGNORECASE,
)
_ANGLE_TITLE_RE = re.compile(r"^<[^<>]{1,120}>$")
_SOURCE_NOTE_MARKERS = (
    "台版 转自",
    "转自 轻之国度",
    "天使动漫",
    "轻之国度×天使动漫录入组",
    "图源：",
    "扫图：",
    "录入：",
    "修图：",
)


def parse_novel_text(text: str) -> list[NovelVolume]:
    if not text.strip():
        return []

    volumes: list[NovelVolume] = []
    current_volume_title = ""
    current_volume_number: int | None = None
    current_chapter_title = ""
    current_chapter_lines: list[str] = []
    current_volume_chapters: list[NovelChapter] = []
    chapter_index = 1
    has_structural_heading = False

    def flush_chapter() -> None:
        nonlocal current_chapter_title, current_chapter_lines, chapter_index
        content, source_notes = _clean_chapter_content(current_chapter_lines)
        if not current_chapter_title and not content:
            current_chapter_lines = []
            return
        current_volume_chapters.append(
            NovelChapter(
                title=current_chapter_title or "正文",
                content=content,
                index=chapter_index,
                source_notes=source_notes,
            )
        )
        chapter_index += 1
        current_chapter_title = ""
        current_chapter_lines = []

    def flush_volume() -> None:
        nonlocal current_volume_title, current_volume_number, current_volume_chapters
        if current_volume_title or current_volume_chapters:
            volumes.append(
                NovelVolume(
                    title=current_volume_title,
                    volume_number=current_volume_number,
                    chapters=current_volume_chapters,
                )
            )
        current_volume_title = ""
        current_volume_number = None
        current_volume_chapters = []

    for line in text.split("\n"):
        stripped = line.strip()
        if not has_structural_heading and (not stripped or _is_preface_line(stripped)):
            continue

        volume_match = _match_volume_heading(stripped)
        if volume_match is not None:
            has_structural_heading = True
            flush_chapter()
            flush_volume()
            current_volume_title = volume_match["title"]
            current_volume_number = volume_match["volume_number"]
            rest = volume_match["rest"]
            if rest and _is_chapter_heading(rest):
                current_chapter_title = rest
            elif rest:
                current_chapter_lines.append(rest)
            continue

        if _is_chapter_heading(stripped):
            has_structural_heading = True
            flush_chapter()
            current_chapter_title = stripped
            continue

        if not has_structural_heading:
            continue
        current_chapter_lines.append(line)

    flush_chapter()
    flush_volume()
    if not volumes and text.strip():
        content, source_notes = _clean_chapter_content(text.split("\n"))
        return [
            NovelVolume(
                title="",
                volume_number=None,
                chapters=[
                    NovelChapter(
                        title="正文",
                        content=content,
                        index=1,
                        source_notes=source_notes,
                    )
                ],
            )
        ]
    return volumes


def _match_volume_heading(stripped: str) -> dict[str, str | int | None] | None:
    if len(stripped) > 60:
        return None
    match = _VOLUME_AT_START_RE.match(stripped)
    if match is None:
        return None
    title = _normalize_heading_token(match.group("title"))
    number_text = match.group("number") or match.group("alt_number")
    volume_number = _parse_number(number_text)
    part = match.group("part")
    if part == "上":
        volume_number = 1
    elif part == "下":
        volume_number = 2
    return {
        "title": title,
        "volume_number": volume_number,
        "rest": (match.group("rest") or "").strip(),
    }


def _is_chapter_heading(stripped: str) -> bool:
    if not stripped or len(stripped) > 60:
        return False
    return _CHAPTER_HEADING_RE.match(stripped) is not None


def _is_preface_line(stripped: str) -> bool:
    return _ANGLE_TITLE_RE.match(stripped) is not None or _is_source_note_line(stripped)


def _clean_chapter_content(lines: list[str]) -> tuple[str, list[str]]:
    kept_lines: list[str] = []
    source_notes: list[str] = []
    for index, line in enumerate(lines):
        if index < 30 and _is_source_note_line(line.strip()):
            source_notes.append(line.strip())
            continue
        kept_lines.append(line)
    return "\n".join(kept_lines).strip(), source_notes


def _is_source_note_line(stripped: str) -> bool:
    return any(marker in stripped for marker in _SOURCE_NOTE_MARKERS)


def _normalize_heading_token(value: str) -> str:
    return re.sub(r"\s+", "", value)


def _parse_number(value: str | None) -> int | None:
    if not value:
        return None
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
                section = (section + number) * unit
                total += section
                section = 0
            else:
                section += (number or 1) * unit
            number = 0
        else:
            return None
    return total + section + number
