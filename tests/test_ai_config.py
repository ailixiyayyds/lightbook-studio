from __future__ import annotations

from pathlib import Path

from app.ai.config import (
    AiProviderConfig,
    get_api_key_from_env,
    load_ai_provider_config,
    save_ai_provider_config,
)
from app.storage import repositories


def test_load_ai_provider_config_returns_defaults(tmp_path: Path) -> None:
    config = load_ai_provider_config(_Repository(tmp_path / "lightbook.db"))

    assert config == AiProviderConfig(
        provider_type="openai_compatible",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-flash",
        api_key_env="LIGHTBOOK_AI_API_KEY",
        timeout_seconds=60,
        temperature=0.2,
    )


def test_save_and_load_ai_provider_config(tmp_path: Path) -> None:
    repository = _Repository(tmp_path / "lightbook.db")
    config = AiProviderConfig(
        provider_type="openai_compatible",
        base_url="https://gateway.example.com/v1",
        model="example-model",
        api_key_env="CUSTOM_LIGHTBOOK_KEY",
        timeout_seconds=30,
        temperature=0.4,
    )

    save_ai_provider_config(repository, config)

    assert load_ai_provider_config(repository) == config
    assert repository.get_setting("ai_provider_type") == "openai_compatible"
    assert repository.get_setting("ai_api_key_env") == "CUSTOM_LIGHTBOOK_KEY"


def test_load_ai_provider_config_migrates_old_mock_when_api_key_exists(
    monkeypatch,
    tmp_path: Path,
) -> None:  # type: ignore[no-untyped-def]
    repository = _Repository(tmp_path / "lightbook.db")
    repository.set_setting("ai_provider_type", "mock")
    monkeypatch.setenv("LIGHTBOOK_AI_API_KEY", "secret-value")

    config = load_ai_provider_config(repository)

    assert config.provider_type == "openai_compatible"
    assert repository.get_setting("ai_provider_type") == "openai_compatible"


def test_get_api_key_from_env(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    config = AiProviderConfig(api_key_env="CUSTOM_LIGHTBOOK_KEY")
    monkeypatch.setenv("CUSTOM_LIGHTBOOK_KEY", "secret-value")

    assert get_api_key_from_env(config) == "secret-value"


def test_save_ai_provider_config_does_not_store_real_api_key(tmp_path: Path) -> None:
    repository = _Repository(tmp_path / "lightbook.db")
    config = AiProviderConfig(api_key_env="CUSTOM_LIGHTBOOK_KEY")

    save_ai_provider_config(repository, config)

    assert repository.get_setting("CUSTOM_LIGHTBOOK_KEY") is None
    assert repository.get_setting("LIGHTBOOK_AI_API_KEY") is None
    assert all("secret" not in value.casefold() for value in repository.settings.values())


class _Repository:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.settings: dict[str, str] = {}

    def get_setting(self, key: str) -> str | None:
        value = repositories.get_setting(key, db_path=self.db_path)
        if value is not None:
            self.settings[key] = value
        return value

    def set_setting(self, key: str, value: str) -> None:
        self.settings[key] = value
        repositories.set_setting(key, value, db_path=self.db_path)
