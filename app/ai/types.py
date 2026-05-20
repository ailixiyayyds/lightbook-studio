from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AiMetadataRequest:
    book_id: int
    media_type: str
    current_metadata: dict[str, Any] = field(default_factory=dict)
    source_info: dict[str, Any] = field(default_factory=dict)
    chapter_titles: list[str] = field(default_factory=list)
    page_count: int | None = None
    text_sample: str = ""
    cover_path: str | None = None


@dataclass(frozen=True)
class AiMetadataResponse:
    raw_text: str
    parsed: dict[str, Any]
    provider: str
    confidence: float
