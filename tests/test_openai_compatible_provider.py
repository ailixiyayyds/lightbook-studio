from __future__ import annotations

from typing import Any

import pytest

from app.ai.openai_compatible_provider import (
    AiProviderConfigurationError,
    OpenAiCompatibleConfig,
    OpenAiCompatibleProvider,
)
from app.ai.types import AiMetadataRequest


def test_openai_compatible_provider_requires_api_key() -> None:
    provider = OpenAiCompatibleProvider(
        OpenAiCompatibleConfig(
            base_url="https://example.test/v1",
            model="test-model",
            api_key=None,
        )
    )

    with pytest.raises(AiProviderConfigurationError, match="LIGHTBOOK_AI_API_KEY"):
        provider.suggest_metadata(_request())


def test_openai_compatible_provider_reads_api_key_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LIGHTBOOK_AI_API_KEY", "secret-key")

    provider = OpenAiCompatibleProvider.from_env(
        base_url="https://example.test/v1",
        model="test-model",
    )

    assert provider.config.api_key == "secret-key"


def test_openai_compatible_provider_parses_json_response() -> None:
    provider = _FakeOpenAiCompatibleProvider(
        OpenAiCompatibleConfig(
            base_url="https://example.test/v1",
            model="test-model",
            api_key="secret-key",
        )
    )

    response = provider.suggest_metadata(_request())

    assert response.provider == "openai_compatible"
    assert response.parsed["clean_title"] == "Clean Title"
    assert response.parsed["tags"] == ["local"]
    assert response.confidence == pytest.approx(0.81)
    assert provider.requested_url == "https://example.test/v1/chat/completions"
    assert provider.requested_payload["model"] == "test-model"


class _FakeOpenAiCompatibleProvider(OpenAiCompatibleProvider):
    def __init__(self, config: OpenAiCompatibleConfig) -> None:
        super().__init__(config)
        self.requested_url = ""
        self.requested_payload: dict[str, Any] = {}

    def _post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.requested_url = url
        self.requested_payload = payload
        return {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"clean_title":"Clean Title","tags":["local"],'
                            '"confidence":0.81}'
                        )
                    }
                }
            ]
        }


def _request() -> AiMetadataRequest:
    return AiMetadataRequest(
        book_id=1,
        media_type="comic",
        current_metadata={"series_title": "Raw"},
        source_info={"source_path": "C:/Books/raw.cbz"},
        page_count=10,
        text_sample="",
        cover_path=None,
    )
