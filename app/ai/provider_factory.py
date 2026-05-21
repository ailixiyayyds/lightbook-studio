from __future__ import annotations

from app.ai.config import AiProviderConfig, get_api_key_from_env
from app.ai.mock_provider import MockAiProvider
from app.ai.openai_compatible_provider import AiProviderConfigError, OpenAICompatibleProvider
from app.ai.provider import BaseAiProvider


def create_ai_provider(config: AiProviderConfig) -> BaseAiProvider:
    provider_type = config.provider_type.strip().lower()
    if provider_type == "openai_compatible":
        return OpenAICompatibleProvider(
            base_url=config.base_url,
            api_key=get_api_key_from_env(config),
            model=config.model,
            timeout_seconds=config.timeout_seconds,
            temperature=config.temperature,
        )
    if provider_type == "mock":
        return MockAiProvider()
    raise AiProviderConfigError(f"Unknown AI provider_type: {config.provider_type}")
