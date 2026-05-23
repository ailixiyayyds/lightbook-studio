from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class MetadataSearchQuery:
    title: str = ""
    original_title: str = ""
    authors: list[str] = field(default_factory=list)
    media_type: str = ""
    language_iso: str = ""
    volume_number: int | None = None
    raw_filename: str = ""
    local_clean_title: str = ""
    book_id: int | None = None


@dataclass(frozen=True)
class MetadataSearchCandidate:
    title: str = ""
    original_title: str = ""
    authors: list[str] = field(default_factory=list)
    publisher: str = ""
    publication_date: str = ""
    isbn: str = ""
    summary: str = ""
    cover_url: str = ""
    source_name: str = ""
    source_url: str = ""
    source_type: str = ""
    genres: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    confidence: float = 0.0
    verified: bool = False
    notes: list[str] = field(default_factory=list)
    # Raw content for AI extraction
    raw_content: str = ""
    raw_content_type: str = ""  # extract, html, wikitext, api_json
    # API response metadata
    categories: list[str] = field(default_factory=list)
    images: list[str] = field(default_factory=list)
    # AI extraction results
    extraction_json: dict = field(default_factory=dict)
    extraction_status: str = ""  # not_extracted, extracted, failed
    extraction_error: str = ""


_SOURCE_TYPE_LABELS: dict[str, str] = {
    "official_publisher": "出版社官网",
    "bookstore": "书城",
    "library_metadata": "图书元数据",
    "community_database": "社区资料库",
    "search_result": "搜索结果",
    "manual": "手动输入",
}


def source_type_label(source_type: str) -> str:
    return _SOURCE_TYPE_LABELS.get(source_type, source_type or "未知来源")


import re

_NOISE_PATTERNS = [
    re.compile(r"^\d+$"),
    re.compile(r"^\d+\s*(gbk|gb18030|utf-?8|big5|shift.jis)$", re.IGNORECASE),
    re.compile(r"^\d+\s*(\.txt|\.epub|\.cbz)$", re.IGNORECASE),
]


def is_valid_search_title(value: str) -> bool:
    stripped = value.strip()
    if not stripped:
        return False
    for pattern in _NOISE_PATTERNS:
        if pattern.fullmatch(stripped):
            return False
    return True
