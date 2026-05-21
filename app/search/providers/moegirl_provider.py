from __future__ import annotations

import logging
from typing import Any

import httpx

from app.search.provider import BaseMetadataSearchProvider
from app.search.types import MetadataSearchCandidate, MetadataSearchQuery, is_valid_search_title

logger = logging.getLogger(__name__)

_MOEGIRL_API = "https://zh.moegirl.org.cn/api.php"
_MAX_RESULTS = 8
_MAX_QUERIES = 12
_MAINTENANCE_CATEGORIES = {"需要", "缺少", "维护", "消歧义", "模板", "帮助", "页面分类", "分类", "含有"}


class MoegirlProvider(BaseMetadataSearchProvider):
    name = "moegirl"

    def __init__(self, timeout_seconds: int = 8) -> None:
        self.timeout_seconds = timeout_seconds
        self._error: str | None = None

    @property
    def last_error(self) -> str | None:
        return self._error

    def search(self, query: MetadataSearchQuery) -> list[MetadataSearchCandidate]:
        self._error = None
        keywords = _build_keywords(query)
        titles_found: set[str] = set()
        candidates: list[MetadataSearchCandidate] = []

        for kw in keywords[:_MAX_QUERIES]:
            page_titles = self._search_titles(kw)
            for pt in page_titles:
                if pt not in titles_found:
                    titles_found.add(pt)

            if len(titles_found) >= _MAX_RESULTS:
                break

        for pt in list(titles_found)[:_MAX_RESULTS]:
            c = self._fetch_page(pt)
            if c is not None:
                candidates.append(c)

        logger.info("Moegirl candidates=%s keywords=%s", len(candidates), len(keywords))
        return candidates

    def _search_titles(self, keyword: str) -> list[str]:
        try:
            response = httpx.get(
                _MOEGIRL_API,
                params={
                    "action": "opensearch",
                    "search": keyword,
                    "limit": "10",
                    "namespace": "0",
                    "format": "json",
                },
                headers={"User-Agent": "LightBookStudio/0.4"},
                timeout=self.timeout_seconds,
                follow_redirects=True,
            )
            if response.status_code < 200 or response.status_code >= 300:
                return []
            data = response.json()
            return [str(t) for t in data[1] if isinstance(t, str)] if len(data) > 1 else []
        except Exception as exc:
            logger.warning("Moegirl opensearch failed: %s", exc)
            return []

    def _fetch_page(self, title: str) -> MetadataSearchCandidate | None:
        try:
            response = httpx.get(
                _MOEGIRL_API,
                params={
                    "action": "query",
                    "prop": "extracts|pageimages|info",
                    "titles": title,
                    "exintro": "1",
                    "explaintext": "1",
                    "piprop": "original|thumbnail",
                    "inprop": "url",
                    "format": "json",
                },
                headers={"User-Agent": "LightBookStudio/0.4"},
                timeout=self.timeout_seconds,
                follow_redirects=True,
            )
            if response.status_code < 200 or response.status_code >= 300:
                return None
            data = response.json()
        except Exception as exc:
            logger.warning("Moegirl page fetch failed title=%s: %s", title, exc)
            return None

        pages = data.get("query", {}).get("pages", {})
        for page_id, page in pages.items():
            if int(page_id) < 0:
                continue

            page_title = str(page.get("title", "")).strip()
            if _is_disambiguation(page_title):
                continue

            extract = str(page.get("extract", "")).strip()[:500]
            images = page.get("original") or page.get("thumbnail") or {}
            cover_url = str(images.get("source", ""))

            fullurl = str(page.get("fullurl", ""))
            source_url = fullurl or f"https://zh.moegirl.org.cn/{page_title}"

            return MetadataSearchCandidate(
                title=page_title,
                summary=extract,
                cover_url=cover_url,
                source_name="萌娘百科",
                source_url=source_url,
                source_type="community_database",
                verified=True,
            )

        return None


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

    return keywords[:_MAX_QUERIES]


def _is_disambiguation(title: str) -> bool:
    return "消歧义" in title or " (消歧义)" in title
