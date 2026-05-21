from __future__ import annotations

from app.search.config import SearchConfig, load_search_config, save_search_config


class _FakeRepository:
    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    def get_setting(self, key: str) -> str | None:
        return self._store.get(key)

    def set_setting(self, key: str, value: str) -> None:
        self._store[key] = value


class TestSearchConfig:

    def test_default_config(self) -> None:
        repo = _FakeRepository()
        config = load_search_config(repo)
        assert config.provider_type == "ai"
        assert config.enabled is True
        assert config.timeout_seconds == 15
        assert config.max_candidates == 6
        assert config.max_detail_pages == 3

    def test_save_and_load_roundtrip(self) -> None:
        repo = _FakeRepository()
        config = SearchConfig(
            provider_type="web",
            enabled=False,
            timeout_seconds=30,
            max_candidates=5,
            max_detail_pages=2,
        )
        save_search_config(repo, config)

        loaded = load_search_config(repo)
        assert loaded.provider_type == "web"
        assert loaded.enabled is False
        assert loaded.timeout_seconds == 30
        assert loaded.max_candidates == 5
        assert loaded.max_detail_pages == 2

    def test_handles_missing_settings(self) -> None:
        repo = _FakeRepository()
        repo.set_setting("search_provider_type", "mock")
        config = load_search_config(repo)
        assert config.provider_type == "mock"
        assert config.enabled is True  # default
        assert config.timeout_seconds == 15  # default

    def test_handles_invalid_int_settings(self) -> None:
        repo = _FakeRepository()
        repo.set_setting("search_timeout_seconds", "not-a-number")
        config = load_search_config(repo)
        assert config.timeout_seconds == 15  # falls back to default

    def test_enabled_false_when_stored_as_false(self) -> None:
        repo = _FakeRepository()
        repo.set_setting("search_enabled", "false")
        config = load_search_config(repo)
        assert config.enabled is False

    def test_enabled_true_when_stored_as_true(self) -> None:
        repo = _FakeRepository()
        repo.set_setting("search_enabled", "true")
        config = load_search_config(repo)
        assert config.enabled is True
