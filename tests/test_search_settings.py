from __future__ import annotations

from pathlib import Path

from app.core.local_secrets import get_secret, has_secret, set_secret
from app.search.config import SearchConfig, load_search_config, save_search_config
from app.search.search_pipeline import _init_providers


class _FakeRepository:
    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    def get_setting(self, key: str) -> str | None:
        return self._store.get(key)

    def set_setting(self, key: str, value: str) -> None:
        self._store[key] = value


def test_full_search_config_roundtrip() -> None:
    repo = _FakeRepository()
    config = SearchConfig(
        provider_type="ai",
        enabled=False,
        ai_query_planner_enabled=False,
        ai_content_extraction_enabled=True,
        content_extract_max_chars=24000,
        content_extract_top_n=5,
        bangumi_enabled=False,
        bangumi_base_url="https://bgm.example.test",
        bangumi_user_agent="LightBookStudio/Test",
        bangumi_timeout_seconds=12,
        bangumi_max_queries=7,
        moegirl_enabled=True,
        moegirl_api_url="https://moe.example.test/api.php",
        moegirl_user_agent="LightBookStudio/MoeTest",
        moegirl_parse_api_enabled=False,
        moegirl_wikitext_fallback_enabled=False,
        moegirl_html_fallback_enabled=True,
        moegirl_max_detail_pages=4,
        moegirl_timeout_seconds=9,
        google_books_enabled=False,
        google_books_api_key_env="GB_KEY",
        google_books_timeout_seconds=13,
        google_books_cooldown_minutes=30,
        ndl_enabled=True,
        ndl_base_url="https://ndl.example.test",
        ndl_timeout_seconds=14,
        open_library_enabled=False,
        open_library_base_url="https://ol.example.test",
        open_library_timeout_seconds=15,
        generic_search_provider="brave",
        generic_search_endpoint="https://search.example.test",
        generic_search_api_key_env="SEARCH_KEY",
        amazon_jp_enabled=False,
    )

    save_search_config(repo, config)
    loaded = load_search_config(repo)

    assert loaded == config


def test_api_key_values_are_not_saved_to_app_settings() -> None:
    repo = _FakeRepository()
    save_search_config(repo, SearchConfig(google_books_api_key_env="GOOGLE_KEY_ENV"))

    assert repo.get_setting("search_google_books_api_key_env") == "GOOGLE_KEY_ENV"
    assert all("secret-api-key" not in value for value in repo._store.values())
    assert "google_books_api_key" not in repo._store


def test_local_secrets_store_is_outside_app_settings(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    set_secret("google_books_api_key", "secret-api-key")

    assert has_secret("google_books_api_key") is True
    assert get_secret("google_books_api_key") == "secret-api-key"
    assert (tmp_path / "data" / "local_secrets.json").exists()


def test_pipeline_provider_settings_are_applied() -> None:
    providers = _init_providers(
        config=SearchConfig(
            bangumi_enabled=True,
            bangumi_base_url="https://bgm.example.test",
            bangumi_user_agent="UA-BGM",
            bangumi_timeout_seconds=11,
            bangumi_max_queries=2,
            moegirl_enabled=True,
            moegirl_api_url="https://moe.example.test/api.php",
            moegirl_user_agent="UA-MOE",
            moegirl_html_fallback_enabled=True,
            moegirl_timeout_seconds=12,
            google_books_enabled=False,
            ndl_enabled=True,
            ndl_base_url="https://ndl.example.test",
            ndl_timeout_seconds=13,
            open_library_enabled=True,
            open_library_base_url="https://ol.example.test",
            open_library_timeout_seconds=14,
            generic_search_provider="brave",
            generic_search_endpoint="https://search.example.test",
            generic_search_api_key_env="SEARCH_KEY",
        )
    )

    by_name = {provider.name: provider for provider in providers}

    assert by_name["bangumi"].base_url == "https://bgm.example.test"
    assert by_name["bangumi"].user_agent == "UA-BGM"
    assert by_name["moegirl"].api_url == "https://moe.example.test/api.php"
    assert by_name["moegirl"].user_agent == "UA-MOE"
    assert by_name["moegirl"].html_fallback_enabled is True
    assert by_name["ndl_search"].base_url == "https://ndl.example.test"
    assert by_name["open_library"].base_url == "https://ol.example.test"
    assert by_name["generic_search"].provider_type == "brave"
    assert by_name["generic_search"].endpoint == "https://search.example.test"
    assert by_name["generic_search"].api_key_env == "SEARCH_KEY"
