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


def test_validate_ai_metadata_rejects_invalid_manga_direction() -> None:
    with pytest.raises(AiMetadataValidationError, match="manga_direction"):
        validate_ai_metadata({"manga_direction": "diagonal"})
