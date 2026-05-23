from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class SearchConfigRepository(Protocol):
    def get_setting(self, key: str) -> str | None: ...
    def set_setting(self, key: str, value: str) -> None: ...


@dataclass(frozen=True)
class SearchConfig:
    provider_type: str = "ai"
    enabled: bool = True
    timeout_seconds: int = 15
    max_candidates: int = 6
    max_detail_pages: int = 3
    ai_query_planner_enabled: bool = True
    ai_content_extraction_enabled: bool = True
    content_extract_max_chars: int = 15000
    content_extract_top_n: int = 3
    bangumi_enabled: bool = True
    bangumi_base_url: str = "https://api.bgm.tv"
    bangumi_user_agent: str = "LightBookStudio/0.4"
    bangumi_timeout_seconds: int = 10
    bangumi_max_queries: int = 4
    moegirl_enabled: bool = True
    moegirl_api_url: str = "https://zh.moegirl.org.cn/api.php"
    moegirl_user_agent: str = "LightBookStudio/0.4"
    moegirl_parse_api_enabled: bool = True
    moegirl_wikitext_fallback_enabled: bool = True
    moegirl_html_fallback_enabled: bool = False
    moegirl_max_detail_pages: int = 3
    moegirl_timeout_seconds: int = 8
    google_books_enabled: bool = True
    google_books_api_key_env: str = "GOOGLE_BOOKS_API_KEY"
    google_books_timeout_seconds: int = 10
    google_books_cooldown_minutes: int = 10
    ndl_enabled: bool = True
    ndl_base_url: str = ""
    ndl_timeout_seconds: int = 10
    open_library_enabled: bool = True
    open_library_base_url: str = "https://openlibrary.org"
    open_library_timeout_seconds: int = 6
    generic_search_provider: str = "disabled"
    generic_search_endpoint: str = ""
    generic_search_api_key_env: str = "LIGHTBOOK_SEARCH_API_KEY"
    amazon_jp_enabled: bool = False


def load_search_config(repository: SearchConfigRepository) -> SearchConfig:
    return SearchConfig(
        provider_type=_setting(repository, "search_provider_type", "ai"),
        enabled=_bool_setting(repository, "search_enabled", True),
        timeout_seconds=_int_setting(repository, "search_timeout_seconds", 15),
        max_candidates=_int_setting(repository, "search_max_candidates", 6),
        max_detail_pages=_int_setting(repository, "search_max_detail_pages", 3),
        ai_query_planner_enabled=_bool_setting(repository, "search_ai_query_planner_enabled", True),
        ai_content_extraction_enabled=_bool_setting(repository, "search_ai_content_extraction_enabled", True),
        content_extract_max_chars=_int_setting(repository, "search_content_extract_max_chars", 15000),
        content_extract_top_n=_int_setting(repository, "search_content_extract_top_n", 3),
        bangumi_enabled=_bool_setting(repository, "search_bangumi_enabled", True),
        bangumi_base_url=_setting(repository, "search_bangumi_base_url", "https://api.bgm.tv"),
        bangumi_user_agent=_setting(repository, "search_bangumi_user_agent", "LightBookStudio/0.4"),
        bangumi_timeout_seconds=_int_setting(repository, "search_bangumi_timeout_seconds", 10),
        bangumi_max_queries=_int_setting(repository, "search_bangumi_max_queries", 4),
        moegirl_enabled=_bool_setting(repository, "search_moegirl_enabled", True),
        moegirl_api_url=_setting(repository, "search_moegirl_api_url", "https://zh.moegirl.org.cn/api.php"),
        moegirl_user_agent=_setting(repository, "search_moegirl_user_agent", "LightBookStudio/0.4"),
        moegirl_parse_api_enabled=_bool_setting(repository, "search_moegirl_parse_api_enabled", True),
        moegirl_wikitext_fallback_enabled=_bool_setting(repository, "search_moegirl_wikitext_fallback_enabled", True),
        moegirl_html_fallback_enabled=_bool_setting(repository, "search_moegirl_html_fallback_enabled", False),
        moegirl_max_detail_pages=_int_setting(repository, "search_moegirl_max_detail_pages", 3),
        moegirl_timeout_seconds=_int_setting(repository, "search_moegirl_timeout_seconds", 8),
        google_books_enabled=_bool_setting(repository, "search_google_books_enabled", True),
        google_books_api_key_env=_setting(repository, "search_google_books_api_key_env", "GOOGLE_BOOKS_API_KEY"),
        google_books_timeout_seconds=_int_setting(repository, "search_google_books_timeout_seconds", 10),
        google_books_cooldown_minutes=_int_setting(repository, "search_google_books_cooldown_minutes", 10),
        ndl_enabled=_bool_setting(repository, "search_ndl_enabled", True),
        ndl_base_url=_setting(repository, "search_ndl_base_url", ""),
        ndl_timeout_seconds=_int_setting(repository, "search_ndl_timeout_seconds", 10),
        open_library_enabled=_bool_setting(repository, "search_open_library_enabled", True),
        open_library_base_url=_setting(repository, "search_open_library_base_url", "https://openlibrary.org"),
        open_library_timeout_seconds=_int_setting(repository, "search_open_library_timeout_seconds", 6),
        generic_search_provider=_setting(repository, "search_generic_provider", "disabled"),
        generic_search_endpoint=_setting(repository, "search_generic_endpoint", ""),
        generic_search_api_key_env=_setting(repository, "search_generic_api_key_env", "LIGHTBOOK_SEARCH_API_KEY"),
        amazon_jp_enabled=_bool_setting(repository, "search_amazon_jp_enabled", False),
    )


def save_search_config(repository: SearchConfigRepository, config: SearchConfig) -> None:
    repository.set_setting("search_provider_type", config.provider_type)
    repository.set_setting("search_enabled", "true" if config.enabled else "false")
    repository.set_setting("search_timeout_seconds", str(config.timeout_seconds))
    repository.set_setting("search_max_candidates", str(config.max_candidates))
    repository.set_setting("search_max_detail_pages", str(config.max_detail_pages))
    repository.set_setting("search_ai_query_planner_enabled", _bool_text(config.ai_query_planner_enabled))
    repository.set_setting("search_ai_content_extraction_enabled", _bool_text(config.ai_content_extraction_enabled))
    repository.set_setting("search_content_extract_max_chars", str(config.content_extract_max_chars))
    repository.set_setting("search_content_extract_top_n", str(config.content_extract_top_n))
    repository.set_setting("search_bangumi_enabled", _bool_text(config.bangumi_enabled))
    repository.set_setting("search_bangumi_base_url", config.bangumi_base_url)
    repository.set_setting("search_bangumi_user_agent", config.bangumi_user_agent)
    repository.set_setting("search_bangumi_timeout_seconds", str(config.bangumi_timeout_seconds))
    repository.set_setting("search_bangumi_max_queries", str(config.bangumi_max_queries))
    repository.set_setting("search_moegirl_enabled", _bool_text(config.moegirl_enabled))
    repository.set_setting("search_moegirl_api_url", config.moegirl_api_url)
    repository.set_setting("search_moegirl_user_agent", config.moegirl_user_agent)
    repository.set_setting("search_moegirl_parse_api_enabled", _bool_text(config.moegirl_parse_api_enabled))
    repository.set_setting("search_moegirl_wikitext_fallback_enabled", _bool_text(config.moegirl_wikitext_fallback_enabled))
    repository.set_setting("search_moegirl_html_fallback_enabled", _bool_text(config.moegirl_html_fallback_enabled))
    repository.set_setting("search_moegirl_max_detail_pages", str(config.moegirl_max_detail_pages))
    repository.set_setting("search_moegirl_timeout_seconds", str(config.moegirl_timeout_seconds))
    repository.set_setting("search_google_books_enabled", _bool_text(config.google_books_enabled))
    repository.set_setting("search_google_books_api_key_env", config.google_books_api_key_env)
    repository.set_setting("search_google_books_timeout_seconds", str(config.google_books_timeout_seconds))
    repository.set_setting("search_google_books_cooldown_minutes", str(config.google_books_cooldown_minutes))
    repository.set_setting("search_ndl_enabled", _bool_text(config.ndl_enabled))
    repository.set_setting("search_ndl_base_url", config.ndl_base_url)
    repository.set_setting("search_ndl_timeout_seconds", str(config.ndl_timeout_seconds))
    repository.set_setting("search_open_library_enabled", _bool_text(config.open_library_enabled))
    repository.set_setting("search_open_library_base_url", config.open_library_base_url)
    repository.set_setting("search_open_library_timeout_seconds", str(config.open_library_timeout_seconds))
    repository.set_setting("search_generic_provider", config.generic_search_provider)
    repository.set_setting("search_generic_endpoint", config.generic_search_endpoint)
    repository.set_setting("search_generic_api_key_env", config.generic_search_api_key_env)
    repository.set_setting("search_amazon_jp_enabled", _bool_text(config.amazon_jp_enabled))


def _setting(repository: SearchConfigRepository, key: str, default: str) -> str:
    value = repository.get_setting(key)
    return value if value is not None and value != "" else default


def _int_setting(repository: SearchConfigRepository, key: str, default: int) -> int:
    try:
        return int(_setting(repository, key, str(default)))
    except (ValueError, TypeError):
        return default


def _bool_setting(repository: SearchConfigRepository, key: str, default: bool) -> bool:
    value = repository.get_setting(key)
    if value is None:
        return default
    return value.casefold() == "true"


def _bool_text(value: bool) -> str:
    return "true" if value else "false"
