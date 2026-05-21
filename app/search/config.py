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


def load_search_config(repository: SearchConfigRepository) -> SearchConfig:
    return SearchConfig(
        provider_type=_setting(repository, "search_provider_type", "ai"),
        enabled=_bool_setting(repository, "search_enabled", True),
        timeout_seconds=_int_setting(repository, "search_timeout_seconds", 15),
        max_candidates=_int_setting(repository, "search_max_candidates", 6),
        max_detail_pages=_int_setting(repository, "search_max_detail_pages", 3),
    )


def save_search_config(repository: SearchConfigRepository, config: SearchConfig) -> None:
    repository.set_setting("search_provider_type", config.provider_type)
    repository.set_setting("search_enabled", "true" if config.enabled else "false")
    repository.set_setting("search_timeout_seconds", str(config.timeout_seconds))
    repository.set_setting("search_max_candidates", str(config.max_candidates))
    repository.set_setting("search_max_detail_pages", str(config.max_detail_pages))


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
