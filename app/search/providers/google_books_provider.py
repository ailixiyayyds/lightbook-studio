from __future__ import annotations

import logging
import os
import json
import time
from typing import Any

import httpx

from app.core.local_secrets import get_secret
from app.search.provider import BaseMetadataSearchProvider
from app.search.types import MetadataSearchCandidate, MetadataSearchQuery, is_valid_search_title

logger = logging.getLogger(__name__)

_GBOOKS_URL = "https://www.googleapis.com/books/v1/volumes"
_MAX_RESULTS = 5
_MAX_REQUESTS = 2
_CACHE_TTL = 600  # 10 minutes
_cache: dict[str, tuple[float, list[MetadataSearchCandidate]]] = {}


class GoogleBooksProvider(BaseMetadataSearchProvider):
    name = "google_books"

    def __init__(self, timeout_seconds: int = 10, api_key_env: str = "GOOGLE_BOOKS_API_KEY") -> None:
        self.timeout_seconds = timeout_seconds
        self._api_key = os.environ.get(api_key_env, "") or get_secret("google_books_api_key")
        self._request_count = 0
        self._error: str | None = None

    @property
    def last_error(self) -> str | None:
        return self._error

    def search(self, query: MetadataSearchQuery) -> list[MetadataSearchCandidate]:
        self._error = None
        self._request_count = 0

        titles = _search_titles(query)
        all_candidates: list[MetadataSearchCandidate] = []
        seen: set[str] = set()

        for title in titles[: _MAX_REQUESTS]:
            if self._request_count >= _MAX_REQUESTS:
                break
            cache_key = f"{title}:{','.join(query.authors[:2])}"
            if cache_key in _cache:
                ts, cached = _cache[cache_key]
                if time.time() - ts < _CACHE_TTL:
                    all_candidates.extend(cached)
                    continue

            candidates = self._do_request(title, query)
            _cache[cache_key] = (time.time(), candidates)
            for c in candidates:
                url_key = c.source_url.strip().lower()
                if url_key and url_key not in seen:
                    seen.add(url_key)
                    all_candidates.append(c)

        return all_candidates[: _MAX_RESULTS]

    def _do_request(self, q: str, query: MetadataSearchQuery) -> list[MetadataSearchCandidate]:
        if self._request_count >= _MAX_REQUESTS:
            return []

        params: dict[str, str | int] = {"q": q, "maxResults": _MAX_RESULTS}
        if self._api_key:
            params["key"] = self._api_key

        self._request_count += 1

        try:
            response = httpx.get(
                _GBOOKS_URL,
                params=params,
                timeout=self.timeout_seconds,
                follow_redirects=True,
            )
        except Exception as exc:
            self._error = f"Google Books 请求失败：{exc}"
            logger.warning("Google Books request failed: %s", exc)
            return []

        if response.status_code == 429:
            self._error = "Google Books 限流 (429)，可配置 GOOGLE_BOOKS_API_KEY 环境变量或稍后重试。"
            logger.warning("Google Books 429 rate limited query=%s", q)
            return []

        if response.status_code < 200 or response.status_code >= 300:
            self._error = f"Google Books HTTP {response.status_code}"
            logger.warning("Google Books HTTP %s query=%s", response.status_code, q)
            return []

        try:
            body = response.json()
        except Exception:
            return []

        return _parse_items(body.get("items", []))


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

    for author in query.authors[:2]:
        for t in [query.title, query.local_clean_title]:
            if t.strip():
                add(f"{t} {author}")

    return titles[: _MAX_REQUESTS]


def _parse_items(items: list[dict[str, Any]]) -> list[MetadataSearchCandidate]:
    result: list[MetadataSearchCandidate] = []
    for item in items[: _MAX_RESULTS]:
        vi = item.get("volumeInfo") or {}
        if not isinstance(vi, dict):
            continue

        title = str(vi.get("title", "")).strip()
        if not title:
            continue

        isbns: list[str] = []
        for ident in vi.get("industryIdentifiers") or []:
            if isinstance(ident, dict):
                isbns.append(f"{ident.get('type', '')}:{ident.get('identifier', '')}")

        images = vi.get("imageLinks") or {}
        image_urls: list[str] = []
        cover_url = ""
        if isinstance(images, dict):
            raw = str(images.get("thumbnail") or images.get("smallThumbnail") or "")
            cover_url = raw.replace("http://", "https://", 1) if raw.startswith("http://") else raw
            for value in images.values():
                image = str(value or "")
                if image.startswith("http://"):
                    image = image.replace("http://", "https://", 1)
                if image and image not in image_urls:
                    image_urls.append(image)

        raw_content_data = {
            "volumeInfo": {
                "title": vi.get("title"),
                "subtitle": vi.get("subtitle"),
                "authors": vi.get("authors"),
                "publisher": vi.get("publisher"),
                "publishedDate": vi.get("publishedDate"),
                "description": vi.get("description"),
                "categories": vi.get("categories"),
            }
        }

        result.append(MetadataSearchCandidate(
            title=title,
            original_title="",
            authors=[str(a).strip() for a in (vi.get("authors") or []) if str(a).strip()],
            publisher=str(vi.get("publisher", "")).strip(),
            publication_date=str(vi.get("publishedDate", "")).strip(),
            isbn=", ".join(isbns),
            summary=str(vi.get("description", "")).strip()[:500],
            cover_url=cover_url,
            source_name="Google Books",
            source_url=str(vi.get("infoLink") or vi.get("canonicalVolumeLink") or ""),
            source_type="library_metadata",
            genres=[str(c).strip() for c in (vi.get("categories") or []) if str(c).strip()],
            tags=[],
            verified=True,
            raw_content=json.dumps(raw_content_data, ensure_ascii=False)[:20000],
            raw_content_type="api_json",
            categories=[str(c).strip() for c in (vi.get("categories") or []) if str(c).strip()],
            images=image_urls,
            extraction_status="not_extracted",
        ))

    return result
