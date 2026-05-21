from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


class AiMetadataValidationError(ValueError):
    """Raised when AI metadata cannot be normalized into the expected schema."""


_LOW_QUALITY_PATTERNS = [
    re.compile(r"这是第\s*\d+\s*卷"),
    re.compile(r"共\s*\d+\s*页"),
    re.compile(r"元数据建议"),
    re.compile(r"metadata\s+suggestion", re.IGNORECASE),
]


_MANGA_DIRECTIONS = {"rtl", "ltr", "webtoon", "unknown"}
_SERIES_STATUSES = {"ongoing", "completed", "hiatus", "unknown"}
_LIST_FIELDS = {
    "aliases",
    "authors",
    "illustrators",
    "translators",
    "genres",
    "tags",
    "content_warnings",
    "notes",
}
_STRING_FIELDS = {
    "clean_title",
    "original_title",
    "book_title",
    "language_iso",
    "summary",
    "manga_direction",
    "series_status",
}


def validate_ai_metadata(data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise AiMetadataValidationError("AI metadata must be a JSON object.")

    result: dict[str, Any] = {
        "clean_title": "",
        "original_title": "",
        "aliases": [],
        "book_title": "",
        "volume_number": None,
        "authors": [],
        "illustrators": [],
        "translators": [],
        "language_iso": "",
        "summary": "",
        "genres": [],
        "tags": [],
        "content_warnings": [],
        "manga_direction": "unknown",
        "series_status": "unknown",
        "confidence": 0.0,
        "field_confidence": {},
        "notes": [],
    }

    for field_name in _STRING_FIELDS:
        if field_name in data:
            result[field_name] = _string_value(data[field_name], field_name)

    for field_name in _LIST_FIELDS:
        if field_name in data:
            result[field_name] = _string_list(data[field_name], field_name)

    if "volume_number" in data:
        result["volume_number"] = _optional_int(data["volume_number"], "volume_number")
    if "confidence" in data:
        result["confidence"] = _clamped_float(data["confidence"], "confidence")
    if "field_confidence" in data:
        result["field_confidence"] = _field_confidence(data["field_confidence"])

    manga_direction = str(result["manga_direction"]).strip().casefold()
    if manga_direction not in _MANGA_DIRECTIONS:
        manga_direction = "unknown"
    result["manga_direction"] = manga_direction

    series_status = str(result["series_status"]).strip().casefold()
    if series_status not in _SERIES_STATUSES:
        series_status = "unknown"
    result["series_status"] = series_status

    return result


def _string_value(value: Any, field_name: str) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return str(value).strip()
    raise AiMetadataValidationError(f"{field_name} must be a string.")


def _string_list(value: Any, field_name: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            if item is None:
                continue
            if not isinstance(item, (str, int, float, bool)):
                raise AiMetadataValidationError(f"{field_name} must contain only string-like values.")
            text = str(item).strip()
            if text:
                result.append(text)
        return result
    raise AiMetadataValidationError(f"{field_name} must be a list of strings.")


def _optional_int(value: Any, field_name: str) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise AiMetadataValidationError(f"{field_name} must be an integer or null.")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise AiMetadataValidationError(f"{field_name} must be an integer or null.") from exc


def _clamped_float(value: Any, field_name: str) -> float:
    if isinstance(value, bool):
        raise AiMetadataValidationError(f"{field_name} must be a number.")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise AiMetadataValidationError(f"{field_name} must be a number.") from exc
    return min(1.0, max(0.0, number))


def _field_confidence(value: Any) -> dict[str, float]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise AiMetadataValidationError("field_confidence must be an object.")
    result: dict[str, float] = {}
    for key, raw_value in value.items():
        field_name = str(key).strip()
        if not field_name:
            continue
        result[field_name] = _clamped_float(raw_value, f"field_confidence.{field_name}")
    return result


def check_summary_quality(summary: str) -> dict[str, Any]:
    """Check if a summary looks low-quality (boilerplate instead of story description).

    Returns a dict with:
      - is_low_quality: bool
      - reasons: list of matched patterns
    """
    if not summary or not summary.strip():
        return {"is_low_quality": False, "reasons": []}
    reasons: list[str] = []
    for pattern in _LOW_QUALITY_PATTERNS:
        if pattern.search(summary):
            reasons.append(pattern.pattern)
    return {"is_low_quality": len(reasons) > 0, "reasons": reasons}
