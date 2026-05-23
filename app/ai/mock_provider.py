from __future__ import annotations

import json
from typing import Any

from app.ai.provider import BaseAiProvider
from app.ai.types import AiMetadataRequest, AiMetadataResponse


class MockAiProvider(BaseAiProvider):
    name = "mock"

    def suggest_metadata(self, request: AiMetadataRequest) -> AiMetadataResponse:
        clean_title = _first_text(
            request.current_metadata.get("series_title"),
            request.current_metadata.get("title"),
            request.current_metadata.get("clean_title"),
            request.source_info.get("filename"),
            request.source_info.get("name"),
            "Untitled",
        )
        book_title = _first_text(
            request.current_metadata.get("book_title"),
            request.current_metadata.get("title"),
            clean_title,
        )
        language_iso = _first_text(request.current_metadata.get("language_iso"), "zh")
        manga_direction = _first_text(request.current_metadata.get("manga_direction"), "rtl")
        is_novel = request.media_type.casefold() == "novel"

        parsed: dict[str, Any] = {
            "clean_title": clean_title,
            "original_title": str(request.current_metadata.get("original_title") or ""),
            "aliases": _list_value(request.current_metadata.get("aliases")),
            "book_title": book_title,
            "volume_number": _optional_int(request.current_metadata.get("volume_number")),
            "authors": _list_value(request.current_metadata.get("author") or request.current_metadata.get("authors")),
            "illustrators": _list_value(request.current_metadata.get("illustrators")),
            "translators": _list_value(
                request.current_metadata.get("translator") or request.current_metadata.get("translators")
            ),
            "language_iso": language_iso,
            "summary": _summary(request, clean_title),
            "genres": _list_value(request.current_metadata.get("genres")) or (["轻小说"] if is_novel else ["漫画"]),
            "tags": _list_value(request.current_metadata.get("tags")) or ["AI建议", "本地整理"],
            "content_warnings": _list_value(request.current_metadata.get("content_warnings")),
            "manga_direction": manga_direction if manga_direction in {"rtl", "ltr", "webtoon"} else "rtl",
            "series_status": str(request.current_metadata.get("series_status") or "unknown"),
            "confidence": 0.72,
            "field_confidence": {
                "clean_title": 0.8,
                "summary": 0.65,
                "genres": 0.7,
                "tags": 0.7,
            },
            "notes": "Mock provider generated this offline suggestion for workflow testing.",
        }
        raw_text = json.dumps(parsed, ensure_ascii=False, sort_keys=True)
        return AiMetadataResponse(
            raw_text=raw_text,
            parsed=parsed,
            provider=self.name,
            confidence=float(parsed["confidence"]),
        )

    def extract_from_content(self, system_prompt: str, user_content: str) -> str:
        """Return deterministic structured extraction for offline workflows."""
        try:
            payload = json.loads(user_content)
        except json.JSONDecodeError:
            payload = {}
        candidate = payload.get("candidate", {}) if isinstance(payload, dict) else {}
        existing = payload.get("existing_candidate_fields", {}) if isinstance(payload, dict) else {}
        images = payload.get("images", []) if isinstance(payload, dict) else []
        categories = payload.get("categories", []) if isinstance(payload, dict) else []
        raw_content = str(payload.get("raw_content", "") if isinstance(payload, dict) else "")
        summary = str(existing.get("summary") or "").strip()
        if not summary and raw_content:
            summary = raw_content.strip().replace("\r\n", "\n").split("\n", 1)[0][:240]
        parsed = {
            "title": str(candidate.get("title") or "").strip(),
            "original_title": "",
            "authors": _list_value(existing.get("authors")),
            "publisher": str(existing.get("publisher") or ""),
            "publication_date": str(existing.get("publication_date") or ""),
            "summary_zh": summary,
            "genres": _list_value(existing.get("genres")) or _list_value(categories)[:3],
            "tags": _list_value(existing.get("tags"))[:10],
            "cover_url_candidates": _list_value(images)[:1],
            "content_warnings": [],
            "match_assessment": {
                "is_likely_same_work": True,
                "reason": "Mock extractor keeps API candidate metadata for workflow testing.",
                "matched_titles": [str(candidate.get("title") or "")],
                "matched_authors": _list_value(existing.get("authors")),
            },
            "translation_notes": [],
            "notes": ["mock extraction"],
        }
        return json.dumps(parsed, ensure_ascii=False, sort_keys=True)


def _first_text(*values: object) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _list_value(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _optional_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _summary(request: AiMetadataRequest, clean_title: str) -> str:
    existing_summary = str(request.current_metadata.get("summary") or "").strip()
    if existing_summary:
        return existing_summary
    if request.media_type.casefold() == "novel":
        chapter_hint = f"，包含 {len(request.chapter_titles)} 个章节标题" if request.chapter_titles else ""
        return f"{clean_title} 的轻小说元数据建议{chapter_hint}。"
    if request.page_count is not None:
        return f"{clean_title} 的漫画元数据建议，共 {request.page_count} 页。"
    return f"{clean_title} 的元数据建议。"
