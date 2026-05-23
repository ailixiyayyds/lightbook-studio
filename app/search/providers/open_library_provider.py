from __future__ import annotations

import logging
import json
import time
from typing import Any

import httpx

from app.search.provider import BaseMetadataSearchProvider
from app.search.types import MetadataSearchCandidate, MetadataSearchQuery, is_valid_search_title

logger = logging.getLogger(__name__)

_OL_SEARCH_URL = "https://openlibrary.org/search.json"
_MAX_RESULTS = 5
_MAX_REQUESTS = 3
_CACHE_TTL = 600
_cache: dict[str, tuple[float, list[MetadataSearchCandidate]]] = {}


class OpenLibraryProvider(BaseMetadataSearchProvider):
    name = "open_library"

    def __init__(self, timeout_seconds: int = 10, base_url: str = "https://openlibrary.org") -> None:
        self.timeout_seconds = timeout_seconds
        self.base_url = base_url.rstrip("/")
        self._error: str | None = None

    @property
    def last_error(self) -> str | None:
        return self._error

    def search(self, query: MetadataSearchQuery) -> list[MetadataSearchCandidate]:
        self._error = None

        titles = _search_titles(query)
        all_candidates: list[MetadataSearchCandidate] = []
        seen_keys: set[str] = set()

        for title in titles[: _MAX_REQUESTS]:
            cache_key = f"{title}"
            if cache_key in _cache:
                ts, cached = _cache[cache_key]
                if time.time() - ts < _CACHE_TTL:
                    all_candidates.extend(cached)
                    continue

            candidates = self._do_request(title, query)
            _cache[cache_key] = (time.time(), candidates)
            for c in candidates:
                key = (c.source_url + c.title).casefold()
                if key not in seen_keys:
                    seen_keys.add(key)
                    all_candidates.append(c)

            if all_candidates:
                break

        if not all_candidates:
            self._error = f"Open Library 未找到匹配结果 (query={titles[0] if titles else query.title})"

        return all_candidates[: _MAX_RESULTS]

    def _do_request(self, title: str, query: MetadataSearchQuery) -> list[MetadataSearchCandidate]:
        params: dict[str, str | int] = {"title": title.strip(), "limit": _MAX_RESULTS}
        if query.authors:
            params["author"] = " ".join(query.authors[:2])

        try:
            response = httpx.get(
                f"{self.base_url}/search.json",
                params=params,
                timeout=self.timeout_seconds,
                follow_redirects=True,
            )
            if response.status_code < 200 or response.status_code >= 300:
                self._error = f"Open Library HTTP {response.status_code}"
                logger.warning("Open Library HTTP %s", response.status_code)
                return []
        except Exception as exc:
            self._error = f"Open Library 请求失败：{exc}"
            logger.warning("Open Library request failed: %s", exc)
            return []

        try:
            body = response.json()
        except Exception:
            return []

        docs = body.get("docs", [])
        logger.info("Open Library docs=%s query=%s", len(docs), title)
        return _parse_docs(docs)


def _search_titles(query: MetadataSearchQuery) -> list[str]:
    titles: list[str] = []
    seen: set[str] = set()

    def add(t: str) -> None:
        t = t.strip()
        if is_valid_search_title(t) and t.casefold() not in seen:
            seen.add(t.casefold())
            titles.append(t)

    add(query.title)
    add(query.local_clean_title)
    add(query.original_title)
    if query.authors:
        for t in [query.title, query.local_clean_title]:
            if t.strip():
                add(f"{t} {query.authors[0]}")

    return titles[: _MAX_REQUESTS]


def _parse_docs(docs: list[dict[str, Any]]) -> list[MetadataSearchCandidate]:
    result: list[MetadataSearchCandidate] = []
    for doc in docs[: _MAX_RESULTS]:
        if not isinstance(doc, dict):
            continue

        title = str(doc.get("title", "")).strip()
        if not title:
            continue

        cover_i = doc.get("cover_i")
        cover_url = f"https://covers.openlibrary.org/b/id/{cover_i}-L.jpg" if cover_i is not None else ""

        ol_key = str(doc.get("key", ""))
        source_url = f"https://openlibrary.org{ol_key}" if ol_key else ""

        isbns: list[str] = []
        for i in doc.get("isbn") or []:
            if i:
                isbns.append(str(i))

        raw_content_data = {
            "title": doc.get("title"),
            "author_name": doc.get("author_name"),
            "publisher": doc.get("publisher"),
            "first_publish_year": doc.get("first_publish_year"),
            "subject": (doc.get("subject") or [])[:30],
            "isbn": (doc.get("isbn") or [])[:10],
        }

        result.append(MetadataSearchCandidate(
            title=title,
            original_title="",
            authors=[str(a).strip() for a in (doc.get("author_name") or []) if str(a).strip()],
            publisher=", ".join(str(p) for p in (doc.get("publisher") or []) if p),
            publication_date=str(doc.get("first_publish_year") or ""),
            isbn=", ".join(isbns),
            summary="",
            cover_url=cover_url,
            source_name="Open Library",
            source_url=source_url,
            source_type="library_metadata",
            genres=[],
            tags=[str(s).strip() for s in (doc.get("subject") or [])[:8] if str(s).strip()],
            verified=True,
            raw_content=json.dumps(raw_content_data, ensure_ascii=False)[:20000],
            raw_content_type="api_json",
            categories=[str(s).strip() for s in (doc.get("subject") or [])[:30] if str(s).strip()],
            images=[cover_url] if cover_url else [],
            extraction_status="not_extracted",
        ))

    return result
