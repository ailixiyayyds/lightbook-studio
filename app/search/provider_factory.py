from __future__ import annotations

from app.ai.config import AiConfigRepository, load_ai_provider_config
from app.core.models import LightBookError
from app.search.ai_search_provider import AiMetadataSearchProvider
from app.search.config import SearchConfig
from app.search.mock_search_provider import MockSearchProvider
from app.search.provider import BaseMetadataSearchProvider
from app.search.web_metadata_search_provider import DuckDuckGoSearchProvider


class SearchProviderFactoryError(LightBookError):
    """Raised when a search provider type is not recognised."""


def create_metadata_search_provider(
    config: SearchConfig,
    ai_repository: AiConfigRepository | None = None,
) -> BaseMetadataSearchProvider:
    provider_type = config.provider_type.strip().casefold()

    if provider_type == "mock":
        return MockSearchProvider()

    if provider_type in ("duckduckgo", "web"):
        return DuckDuckGoSearchProvider(
            timeout_seconds=config.timeout_seconds,
            max_candidates=config.max_candidates,
            max_detail_pages=config.max_detail_pages,
        )

    if provider_type == "ai":
        if ai_repository is None:
            raise SearchProviderFactoryError(
                "AI 搜索 provider 需要 AiConfigRepository。"
            )
        ai_config = load_ai_provider_config(ai_repository)
        return AiMetadataSearchProvider(ai_config)

    raise SearchProviderFactoryError(
        f"未知搜索 provider 类型：{config.provider_type}。"
        f"支持的类型：ai, duckduckgo, web, mock。"
    )
