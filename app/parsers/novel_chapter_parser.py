from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class NovelChapter:
    title: str
    content: str
    order_index: int
    source_notes: list[str] = field(default_factory=list)

    @property
    def index(self) -> int:
        return self.order_index


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
_VOLUME_AT_START_RE = re.compile(
    rf"^\s*(?P<title>第\s*(?P<number>{_NUMBER_TEXT})\s*卷|卷\s*(?P<alt_number>{_NUMBER_TEXT})|(?P<part>[上中下])卷|短篇集|番外篇)"
    rf"(?:\s+(?P<rest>.+))?\s*$"
)
_VOLUME_ONLY_RE = re.compile(
    rf"^(?:第\s*(?P<di_number>{_NUMBER_TEXT})\s*卷|卷\s*(?P<juan_number>{_NUMBER_TEXT})|(?P<part>[上中下])卷|短篇集|番外篇)$",
    re.IGNORECASE,
)
_CHAPTER_HEADING_RE = re.compile(
    rf"^(?:"
    rf"(?:序章|楔子|前言|终章|后记|尾声|插图|幕间|间章)(?:\s+.+)?"
    rf"|第\s*(?:{_NUMBER_TEXT})\s*[章节話话](?:\s+.+)?"
    rf"|chapter\s+0*\d+(?:\s+.+)?"
    rf")$",
    re.IGNORECASE,
)
_ANGLE_TITLE_RE = re.compile(r"^\s*<(?P<value>[^<>]{1,120})>\s*$")
_TITLE_RE = re.compile(
    r"^\s*(?:书名|書名|作品名|小说名称|小說名稱|小说名|小說名|标题|標題)\s*[:：]\s*(?P<value>.+?)\s*$"
)
_AUTHOR_RE = re.compile(r"^\s*(?:作者|作\s*者)\s*[:：]\s*(?P<value>.+?)\s*$")
_WENKU8_BANNER_RE = re.compile(r"轻小说文库\s*\(\s*www\.wenku8\.com\s*\)", re.IGNORECASE)
_SOURCE_NOTE_MARKERS = (
    "台版 转自",
    "转自 轻之国度",
    "天使动漫",
    "轻之国度×天使动漫录入组",
    "图源：",
    "图源:",
    "扫图：",
    "扫图:",
    "录入：",
    "录入:",
    "修图：",
    "修图:",
)


def parse_novel_text(text: str) -> NovelParseResult:
    normalized = _normalize_newlines(text)
    title_guess, author_guess = _guess_metadata(normalized)
    warnings: list[str] = []

    if not normalized.strip():
        warnings.append("文本为空。")
        return NovelParseResult(
            title_guess=title_guess,
            author_guess=author_guess,
            volumes=[],
            warnings=warnings,
        )

    volumes: list[NovelVolume] = []
    current_volume_title = ""
    current_volume_number: int | None = None
    current_chapter_title = ""
    current_chapter_lines: list[str] = []
    current_volume_chapters: list[NovelChapter] = []
    order_index = 1
    has_structural_heading = False
    saw_chapter_heading = False
    saw_volume_heading = False

    def flush_chapter() -> None:
        nonlocal current_chapter_title, current_chapter_lines, order_index
        content, source_notes = _clean_chapter_content(current_chapter_lines)
        if not current_chapter_title and not content:
            current_chapter_lines = []
            return
        current_volume_chapters.append(
            NovelChapter(
                title=current_chapter_title or "正文",
                content=content,
                order_index=order_index,
                source_notes=source_notes,
            )
        )
        order_index += 1
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

    for line in normalized.split("\n"):
        stripped = line.strip()
        if not has_structural_heading and (not stripped or _is_preface_line(stripped)):
            continue

        volume_match = _match_volume_heading(stripped)
        if volume_match is not None:
            saw_volume_heading = True
            has_structural_heading = True
            flush_chapter()
            flush_volume()
            current_volume_title = str(volume_match["title"])
            current_volume_number = _as_optional_int(volume_match["volume_number"])
            rest = str(volume_match["rest"] or "").strip()
            if rest and _is_chapter_heading(rest):
                saw_chapter_heading = True
                current_chapter_title = rest
            elif rest:
                current_chapter_lines.append(rest)
            continue

        if _is_chapter_heading(stripped):
            saw_chapter_heading = True
            has_structural_heading = True
            flush_chapter()
            current_chapter_title = stripped
            continue

        if not has_structural_heading:
            continue
        current_chapter_lines.append(line)

    flush_chapter()
    flush_volume()

    if not saw_chapter_heading:
        fallback_content, source_notes = _clean_chapter_content(normalized.split("\n"))
        warnings.append("未识别到章节标题，已生成默认章节。")
        volumes = [
            NovelVolume(
                title="",
                volume_number=None,
                chapters=[
                    NovelChapter(
                        title="正文",
                        content=fallback_content,
                        order_index=1,
                        source_notes=source_notes,
                    )
                ],
            )
        ]
    elif not saw_volume_heading:
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
        warnings=warnings,
    )


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _match_volume_heading(stripped: str) -> dict[str, str | int | None] | None:
    if not _is_title_length_ok(stripped):
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


def _parse_volume_heading(stripped: str) -> tuple[str, int | None] | None:
    if not _is_title_length_ok(stripped):
        return None
    match = _VOLUME_ONLY_RE.fullmatch(stripped)
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
    return _normalize_heading_token(stripped), volume_number


def _is_chapter_heading(stripped: str) -> bool:
    if not _is_title_length_ok(stripped):
        return False
    return _CHAPTER_HEADING_RE.fullmatch(stripped) is not None


def _is_title_length_ok(value: str) -> bool:
    if not value:
        return False
    compact = re.sub(r"\s+", "", value)
    return len(compact) <= 60


def _is_preface_line(stripped: str) -> bool:
    return (
        _ANGLE_TITLE_RE.match(stripped) is not None
        or _WENKU8_BANNER_RE.search(stripped) is not None
        or _is_source_note_line(stripped)
    )


def _clean_chapter_content(lines: list[str]) -> tuple[str, list[str]]:
    kept_lines: list[str] = []
    source_notes: list[str] = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        if index < 30 and _is_source_note_line(stripped):
            source_notes.append(stripped)
            continue
        kept_lines.append(line)
    return "\n".join(kept_lines).strip(), source_notes


def _is_source_note_line(stripped: str) -> bool:
    return any(marker in stripped for marker in _SOURCE_NOTE_MARKERS)


def _guess_metadata(text: str) -> tuple[str, str]:
    title_guess = ""
    author_guess = ""
    for line in text.split("\n")[:80]:
        if not title_guess:
            angle_match = _ANGLE_TITLE_RE.match(line)
            if angle_match:
                title_guess = _main_title(angle_match.group("value").strip())
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


def _main_title(value: str) -> str:
    for open_bracket, close_bracket in (("(", ")"), ("（", "）")):
        if open_bracket in value and value.endswith(close_bracket):
            main_title = value.rsplit(open_bracket, 1)[0].strip()
            if main_title:
                return main_title
    return value


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
                total += (section + number) * unit
                section = 0
            else:
                section += (number or 1) * unit
            number = 0
        else:
            return None
    return total + section + number


def _as_optional_int(value: object) -> int | None:
    if value is None:
        return None
    return int(value)
