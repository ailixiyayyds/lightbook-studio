from __future__ import annotations

import pytest

from app.ai.config import AiProviderConfig
from app.ai.mock_provider import MockAiProvider
from app.ai.openai_compatible_provider import AiProviderConfigError, OpenAICompatibleProvider
from app.ai.provider_factory import create_ai_provider


def test_create_ai_provider_returns_mock_provider() -> None:
    provider = create_ai_provider(AiProviderConfig(provider_type="mock"))

    assert isinstance(provider, MockAiProvider)


def test_create_ai_provider_returns_openai_compatible_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CUSTOM_LIGHTBOOK_KEY", "secret-value")
    config = AiProviderConfig(
        provider_type="openai_compatible",
        base_url="https://gateway.example.com",
        model="example-model",
        api_key_env="CUSTOM_LIGHTBOOK_KEY",
        timeout_seconds=12,
        temperature=0.3,
    )

    provider = create_ai_provider(config)

    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.base_url == "https://gateway.example.com"
    assert provider.model == "example-model"
    assert provider.api_key == "secret-value"
    assert provider.timeout_seconds == 12
    assert provider.temperature == 0.3


def test_create_ai_provider_normalizes_provider_type_case_and_spaces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CUSTOM_LIGHTBOOK_KEY", "secret-value")

    provider = create_ai_provider(
        AiProviderConfig(
            provider_type="  OpenAI_Compatible  ",
            api_key_env="CUSTOM_LIGHTBOOK_KEY",
        )
    )

    assert isinstance(provider, OpenAICompatibleProvider)


def test_create_ai_provider_rejects_unknown_provider() -> None:
    with pytest.raises(AiProviderConfigError, match="Unknown AI provider_type"):
        create_ai_provider(AiProviderConfig(provider_type="unknown"))


def test_create_ai_provider_allows_missing_api_key_until_provider_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CUSTOM_LIGHTBOOK_KEY", raising=False)
    provider = create_ai_provider(
        AiProviderConfig(
            provider_type="openai_compatible",
            api_key_env="CUSTOM_LIGHTBOOK_KEY",
        )
    )

    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.api_key == ""
