from __future__ import annotations

import pytest

from app.search.ai_search_provider import AiMetadataSearchProvider
from app.search.config import SearchConfig
from app.search.mock_search_provider import MockSearchProvider
from app.search.provider_factory import (
    SearchProviderFactoryError,
    create_metadata_search_provider,
)
from app.search.web_metadata_search_provider import DuckDuckGoSearchProvider


class _FakeAiRepository:
    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    def get_setting(self, key: str) -> str | None:
        return self._store.get(key)

    def set_setting(self, key: str, value: str) -> None:
        self._store[key] = value


class TestCreateMetadataSearchProvider:

    def test_ai_type_requires_repository(self) -> None:
        config = SearchConfig(provider_type="ai")
        with pytest.raises(SearchProviderFactoryError, match="AiConfigRepository"):
            create_metadata_search_provider(config)

    def test_ai_type_with_repository_returns_ai_provider(self) -> None:
        config = SearchConfig(provider_type="ai")
        repo = _FakeAiRepository()
        provider = create_metadata_search_provider(config, ai_repository=repo)
        assert isinstance(provider, AiMetadataSearchProvider)

    def test_web_type_returns_duckduckgo_provider(self) -> None:
        config = SearchConfig(provider_type="web")
        provider = create_metadata_search_provider(config)
        assert isinstance(provider, DuckDuckGoSearchProvider)

    def test_duckduckgo_type_returns_duckduckgo_provider(self) -> None:
        config = SearchConfig(provider_type="duckduckgo")
        provider = create_metadata_search_provider(config)
        assert isinstance(provider, DuckDuckGoSearchProvider)

    def test_mock_type_returns_mock_provider(self) -> None:
        config = SearchConfig(provider_type="mock")
        provider = create_metadata_search_provider(config)
        assert isinstance(provider, MockSearchProvider)

    def test_strips_whitespace_and_case_for_duckduckgo(self) -> None:
        config = SearchConfig(provider_type="  DuckDuckGo  ")
        provider = create_metadata_search_provider(config)
        assert isinstance(provider, DuckDuckGoSearchProvider)

    def test_unknown_provider_raises(self) -> None:
        config = SearchConfig(provider_type="google")
        with pytest.raises(SearchProviderFactoryError, match="未知搜索 provider"):
            create_metadata_search_provider(config)

    def test_passes_config_values_to_duckduckgo_provider(self) -> None:
        config = SearchConfig(
            provider_type="duckduckgo",
            timeout_seconds=30,
            max_candidates=5,
            max_detail_pages=2,
        )
        provider = create_metadata_search_provider(config)
        assert provider.timeout_seconds == 30
        assert provider.max_candidates == 5
        assert provider.max_detail_pages == 2
