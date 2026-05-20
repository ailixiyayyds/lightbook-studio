from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from app.core.models import ImporterError
from app.utils.novel_chapter_parser import NovelVolume, parse_novel_text
from app.utils.text_cleaner import clean_novel_text
from app.utils.text_encoding import detect_and_read_text
from app.utils.wenku8_filename import parse_wenku8_txt_filename


@dataclass(frozen=True)
class NovelImportResult:
    source_path: Path
    source_type: str = field(default="novel_txt", init=False)
    source_file_id: str | None = None
    source_book_id: str | None = None
    encoding: str = ""
    title_guess: str = ""
    author_guess: str = ""
    volumes: list[NovelVolume] = field(default_factory=list)
    text_length: int = 0
    chapter_count: int = 0
    warnings: list[str] = field(default_factory=list)


class NovelTxtImporter:
    def import_file(self, path: str | Path) -> NovelImportResult:
        return import_novel_txt(path)


def import_novel_txt(path: str | Path) -> NovelImportResult:
    source_path = Path(path)
    if not source_path.exists():
        raise ImporterError(f"TXT 文件不存在：{source_path}")
    if not source_path.is_file():
        raise ImporterError(f"路径不是 TXT 文件：{source_path}")
    if source_path.suffix.casefold() != ".txt":
        raise ImporterError(f"文件不是 .txt：{source_path}")

    filename_info = parse_wenku8_txt_filename(source_path.name)
    raw_text, encoding = detect_and_read_text(source_path)
    cleaned_text = clean_novel_text(raw_text)
    volumes = parse_novel_text(cleaned_text)
    title_guess, author_guess, source_book_id = _guess_metadata(cleaned_text)
    chapter_count = sum(len(volume.chapters) for volume in volumes)

    warnings: list[str] = []
    if not title_guess:
        warnings.append("未能从正文推测标题。")
    if chapter_count == 0:
        warnings.append("未能解析到章节。")

    return NovelImportResult(
        source_path=source_path,
        source_file_id=filename_info.source_file_id,
        source_book_id=source_book_id,
        encoding=encoding,
        title_guess=title_guess,
        author_guess=author_guess,
        volumes=volumes,
        text_length=len(cleaned_text),
        chapter_count=chapter_count,
        warnings=warnings,
    )


_ANGLE_TITLE_RE = re.compile(r"^\s*<(?P<value>[^<>]{1,120})>\s*$")
_TITLE_RE = re.compile(
    r"^\s*(?:书名|書名|作品名|小说名称|小說名稱|小说名|小說名|标题|標題)\s*[:：]\s*(?P<value>.+?)\s*$"
)
_AUTHOR_RE = re.compile(r"^\s*(?:作者|作\s*者)\s*[:：]\s*(?P<value>.+?)\s*$")
_SOURCE_BOOK_ID_RE = re.compile(
    r"^\s*(?:小说编号|小說編號|书籍编号|書籍編號|作品编号|作品編號|book[_\s-]*id)\s*[:：]\s*(?P<value>\d+)\s*$",
    re.IGNORECASE,
)


def _guess_metadata(text: str) -> tuple[str, str, str | None]:
    title_guess = ""
    author_guess = ""
    source_book_id: str | None = None

    non_empty_lines = [line for line in text.split("\n") if line.strip()]
    for line in non_empty_lines[:80]:
        if not title_guess:
            angle_title_match = _ANGLE_TITLE_RE.match(line)
            if angle_title_match:
                title_guess = _main_title(angle_title_match.group("value").strip())
            else:
                title_match = _TITLE_RE.match(line)
                if title_match:
                    title_guess = title_match.group("value").strip()
        if not author_guess:
            author_match = _AUTHOR_RE.match(line)
            if author_match:
                author_guess = author_match.group("value").strip()
        if source_book_id is None:
            source_book_id_match = _SOURCE_BOOK_ID_RE.match(line)
            if source_book_id_match:
                source_book_id = source_book_id_match.group("value")
        if title_guess and author_guess and source_book_id is not None:
            break

    return title_guess, author_guess, source_book_id


def _main_title(value: str) -> str:
    for open_bracket, close_bracket in (("(", ")"), ("（", "）")):
        if open_bracket in value and value.endswith(close_bracket):
            main_title = value.rsplit(open_bracket, 1)[0].strip()
            if main_title:
                return main_title
    return value
