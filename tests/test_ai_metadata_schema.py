from __future__ import annotations

import pytest

from app.ai.metadata_schema import AiMetadataValidationError, validate_ai_metadata


def test_validate_ai_metadata_accepts_complete_valid_json() -> None:
    result = validate_ai_metadata(
        {
            "clean_title": "Clean",
            "original_title": "Original",
            "aliases": ["Alias"],
            "book_title": "Book",
            "volume_number": 2,
            "authors": ["Author"],
            "illustrators": ["Illustrator"],
            "translators": ["Translator"],
            "language_iso": "zh",
            "summary": "Summary",
            "genres": ["Fantasy"],
            "tags": ["Magic"],
            "content_warnings": ["Violence"],
            "manga_direction": "rtl",
            "series_status": "ongoing",
            "confidence": 0.8,
            "field_confidence": {"clean_title": 0.9},
            "notes": ["Looks good"],
        }
    )

    assert result["clean_title"] == "Clean"
    assert result["volume_number"] == 2
    assert result["tags"] == ["Magic"]
    assert result["manga_direction"] == "rtl"
    assert result["series_status"] == "ongoing"
    assert result["confidence"] == 0.8
    assert result["field_confidence"] == {"clean_title": 0.9}
    assert result["notes"] == ["Looks good"]


def test_validate_ai_metadata_fills_missing_fields() -> None:
    result = validate_ai_metadata({"clean_title": "Only Title"})

    assert result["clean_title"] == "Only Title"
    assert result["aliases"] == []
    assert result["volume_number"] is None
    assert result["manga_direction"] == "unknown"
    assert result["series_status"] == "unknown"
    assert result["confidence"] == 0.0
    assert result["field_confidence"] == {}
    assert result["notes"] == []


def test_validate_ai_metadata_splits_string_tags() -> None:
    result = validate_ai_metadata({"tags": "fantasy, school,  magic "})

    assert result["tags"] == ["fantasy", "school", "magic"]


def test_validate_ai_metadata_clamps_confidence() -> None:
    high = validate_ai_metadata({"confidence": 1.5})
    low = validate_ai_metadata({"confidence": -0.25})

    assert high["confidence"] == 1.0
    assert low["confidence"] == 0.0


def test_validate_ai_metadata_defaults_invalid_manga_direction_to_unknown() -> None:
    result = validate_ai_metadata({"manga_direction": "diagonal"})
    assert result["manga_direction"] == "unknown"


def test_validate_ai_metadata_defaults_invalid_series_status_to_unknown() -> None:
    result = validate_ai_metadata({"series_status": "cancelled"})
    assert result["series_status"] == "unknown"


def test_validate_ai_metadata_accepts_string_genres() -> None:
    result = validate_ai_metadata({"genres": "漫画, 百合, 校园"})
    assert result["genres"] == ["漫画", "百合", "校园"]


def test_validate_ai_metadata_accepts_string_authors() -> None:
    result = validate_ai_metadata({"authors": "池田學志, 作者B"})
    assert result["authors"] == ["池田學志", "作者B"]


def test_check_summary_quality_detects_boilerplate() -> None:
    from app.ai.metadata_schema import check_summary_quality

    assert check_summary_quality("这是第04卷")["is_low_quality"] is True
    assert check_summary_quality("共 166 页")["is_low_quality"] is True
    assert check_summary_quality("漫画元数据建议")["is_low_quality"] is True
    assert check_summary_quality("")["is_low_quality"] is False


def test_check_summary_quality_passes_real_summary() -> None:
    from app.ai.metadata_schema import check_summary_quality

    result = check_summary_quality("主角是一个普通高中生，某天遇到了来自异世界的少女。")
    assert result["is_low_quality"] is False
