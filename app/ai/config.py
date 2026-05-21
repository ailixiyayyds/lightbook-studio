from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol


DEFAULT_AI_PROVIDER_TYPE = "openai_compatible"
DEFAULT_AI_BASE_URL = "https://api.deepseek.com"
DEFAULT_AI_MODEL = "deepseek-v4-flash"
DEFAULT_AI_API_KEY_ENV = "LIGHTBOOK_AI_API_KEY"
DEFAULT_AI_TIMEOUT_SECONDS = 60
DEFAULT_AI_TEMPERATURE = 0.2


class AiConfigRepository(Protocol):
    def get_setting(self, key: str) -> str | None: ...

    def set_setting(self, key: str, value: str) -> None: ...


@dataclass(frozen=True)
class AiProviderConfig:
    provider_type: str = DEFAULT_AI_PROVIDER_TYPE
    base_url: str = DEFAULT_AI_BASE_URL
    model: str = DEFAULT_AI_MODEL
    api_key_env: str = DEFAULT_AI_API_KEY_ENV
    timeout_seconds: int = DEFAULT_AI_TIMEOUT_SECONDS
    temperature: float = DEFAULT_AI_TEMPERATURE


def load_ai_provider_config(repository: AiConfigRepository) -> AiProviderConfig:
    api_key_env = _setting(repository, "ai_api_key_env", DEFAULT_AI_API_KEY_ENV)
    provider_type = _setting(repository, "ai_provider_type", DEFAULT_AI_PROVIDER_TYPE).strip().lower()
    if provider_type == "mock" and os.environ.get(api_key_env):
        provider_type = "openai_compatible"
        repository.set_setting("ai_provider_type", provider_type)

    return AiProviderConfig(
        provider_type=provider_type,
        base_url=_setting(repository, "ai_base_url", DEFAULT_AI_BASE_URL),
        model=_setting(repository, "ai_model", DEFAULT_AI_MODEL),
        api_key_env=api_key_env,
        timeout_seconds=_int_setting(
            repository,
            "ai_timeout_seconds",
            DEFAULT_AI_TIMEOUT_SECONDS,
        ),
        temperature=_float_setting(
            repository,
            "ai_temperature",
            DEFAULT_AI_TEMPERATURE,
        ),
    )


def save_ai_provider_config(repository: AiConfigRepository, config: AiProviderConfig) -> None:
    repository.set_setting("ai_provider_type", config.provider_type.strip().lower())
    repository.set_setting("ai_base_url", config.base_url)
    repository.set_setting("ai_model", config.model)
    repository.set_setting("ai_api_key_env", config.api_key_env)
    repository.set_setting("ai_timeout_seconds", str(int(config.timeout_seconds)))
    repository.set_setting("ai_temperature", str(float(config.temperature)))


def get_api_key_from_env(config: AiProviderConfig) -> str:
    return os.environ.get(config.api_key_env, "")


def _setting(repository: AiConfigRepository, key: str, default: str) -> str:
    value = repository.get_setting(key)
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def _int_setting(repository: AiConfigRepository, key: str, default: int) -> int:
    value = repository.get_setting(key)
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float_setting(repository: AiConfigRepository, key: str, default: float) -> float:
    value = repository.get_setting(key)
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
