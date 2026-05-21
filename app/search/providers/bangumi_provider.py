from __future__ import annotations

import logging
from typing import Any

import httpx

from app.search.provider import BaseMetadataSearchProvider
from app.search.types import MetadataSearchCandidate, MetadataSearchQuery, is_valid_search_title

logger = logging.getLogger(__name__)

_BGM_SEARCH_URL = "https://api.bgm.tv/v0/search/subjects"
_BGM_MAX_RESULTS = 8

_BGM_SUBJECT_TYPES = {1: "book", 2: "anime", 3: "music", 4: "game", 6: "real"}


class BangumiProvider(BaseMetadataSearchProvider):
    name = "bangumi"

    def __init__(self, timeout_seconds: int = 10) -> None:
        self.timeout_seconds = timeout_seconds
        self._error: str | None = None

    @property
    def last_error(self) -> str | None:
        return self._error

    def search(self, query: MetadataSearchQuery) -> list[MetadataSearchCandidate]:
        self._error = None
        keywords = _build_keywords(query)
        all_candidates: list[MetadataSearchCandidate] = []
        seen: set[str] = set()

        for kw in keywords[:4]:
            try:
                response = httpx.post(
                    _BGM_SEARCH_URL,
                    json={
                        "keyword": kw,
                        "sort": "match",
                        "filter": {"type": [1]},
                    },
                    headers={
                        "User-Agent": "LightBookStudio/0.4",
                        "Content-Type": "application/json",
                    },
                    timeout=self.timeout_seconds,
                    follow_redirects=True,
                )
                if response.status_code < 200 or response.status_code >= 300:
                    self._error = f"Bangumi HTTP {response.status_code}"
                    logger.warning("Bangumi HTTP %s query=%s", response.status_code, kw)
                    continue
            except Exception as exc:
                self._error = f"Bangumi 请求失败：{exc}"
                logger.warning("Bangumi request failed: %s", exc)
                continue

            try:
                body = response.json()
            except Exception:
                continue

            for item in body.get("data", [])[: _BGM_MAX_RESULTS]:
                c = _parse_item(item)
                if c is None:
                    continue
                key = c.source_url.lower()
                if key not in seen:
                    seen.add(key)
                    all_candidates.append(c)

            if all_candidates:
                break

        logger.info("Bangumi candidates=%s queries=%s", len(all_candidates), len(keywords))
        return all_candidates[: _BGM_MAX_RESULTS]


def _build_keywords(query: MetadataSearchQuery) -> list[str]:
    keywords: list[str] = []
    seen: set[str] = set()

    def add(k: str) -> None:
        k = k.strip()
        if is_valid_search_title(k) and k.casefold() not in seen:
            seen.add(k.casefold())
            keywords.append(k)

    add(query.local_clean_title)
    add(query.title)
    add(query.original_title)
    for author in query.authors[:2]:
        for t in [query.local_clean_title, query.title]:
            if t.strip():
                add(f"{t} {author}")

    return keywords[:4]


def _parse_item(item: dict[str, Any]) -> MetadataSearchCandidate | None:
    subj_id = item.get("id")
    if subj_id is None:
        return None

    title = str(item.get("name", "")).strip()
    name_cn = str(item.get("name_cn", "")).strip()
    if name_cn and name_cn != title:
        display_title = f"{title}（{name_cn}）"
    else:
        display_title = title or name_cn or ""

    if not display_title.strip():
        return None

    images = item.get("images") or {}
    cover_url = str(images.get("large") or images.get("common") or images.get("medium") or "")

    summary = str(item.get("summary", "")).strip()[:500]

    return MetadataSearchCandidate(
        title=display_title,
        original_title=title if title != display_title else "",
        authors=[],
        publisher="",
        summary=summary,
        cover_url=cover_url,
        source_name="Bangumi",
        source_url=f"https://bgm.tv/subject/{subj_id}",
        source_type="community_database",
        genres=[],
        tags=[],
        verified=True,
    )
