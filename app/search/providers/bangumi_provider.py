"""Bangumi (bangumi.tv) metadata search provider.

Uses Bangumi API v0 to search and fetch subject details.
Supports content extraction by fetching subject details including
summary, infobox, tags, and images.

API endpoints:
- Search: POST https://api.bgm.tv/v0/search/subjects
- Detail: GET https://api.bgm.tv/v0/subjects/{id}
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.search.provider import BaseMetadataSearchProvider
from app.search.types import MetadataSearchCandidate, MetadataSearchQuery, is_valid_search_title

logger = logging.getLogger(__name__)

_BGM_BASE_URL = "https://api.bgm.tv"
_BGM_MAX_RESULTS = 8
_BGM_TIMEOUT = 10

_USER_AGENT = "LightBookStudio/0.4"

# Subject type 1 = book (includes manga and novels)
_BGM_SUBJECT_TYPE_BOOK = 1


class BangumiProvider(BaseMetadataSearchProvider):
    """Metadata search provider for Bangumi using API v0."""

    name = "bangumi"

    def __init__(
        self,
        timeout_seconds: int = _BGM_TIMEOUT,
        content_extractor: Any | None = None,
        base_url: str = _BGM_BASE_URL,
        user_agent: str = _USER_AGENT,
        max_queries: int = 4,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.content_extractor = content_extractor
        self.base_url = base_url.rstrip("/")
        self.user_agent = user_agent or _USER_AGENT
        self.max_queries = max(1, max_queries)
        self._error: str | None = None

    @property
    def last_error(self) -> str | None:
        return self._error

    def search(self, query: MetadataSearchQuery) -> list[MetadataSearchCandidate]:
        """Search for metadata candidates from Bangumi."""
        self._error = None
        keywords = _build_keywords(query)
        all_candidates: list[MetadataSearchCandidate] = []
        seen: set[str] = set()

        logger.info(
            "Bangumi search start keywords=%s title=%s",
            len(keywords),
            query.title,
        )

        for kw in keywords[: self.max_queries]:
            try:
                response = httpx.post(
                    f"{self.base_url}/v0/search/subjects",
                    json={
                        "keyword": kw,
                        "sort": "match",
                        "filter": {"type": [_BGM_SUBJECT_TYPE_BOOK]},
                    },
                    headers={
                        "User-Agent": self.user_agent,
                        "Content-Type": "application/json",
                    },
                    timeout=self.timeout_seconds,
                    follow_redirects=True,
                )
                if response.status_code < 200 or response.status_code >= 300:
                    self._error = f"Bangumi HTTP {response.status_code}"
                    logger.warning(
                        "Bangumi HTTP %s query=%s",
                        response.status_code,
                        kw,
                    )
                    continue
            except Exception as exc:
                self._error = f"Bangumi request failed: {exc}"
                logger.warning("Bangumi request failed: %s", exc)
                continue

            try:
                body = response.json()
            except Exception:
                continue

            for item in body.get("data", [])[: _BGM_MAX_RESULTS]:
                subj_id = item.get("id")
                if subj_id is None:
                    continue

                # Fetch subject details
                candidate = self._fetch_subject_detail(subj_id, item)
                if candidate is None:
                    continue

                candidate = self.enrich_candidate(query, candidate)
                key = candidate.source_url.lower()
                if key not in seen:
                    seen.add(key)
                    all_candidates.append(candidate)

            if len(all_candidates) >= _BGM_MAX_RESULTS:
                break

        logger.info(
            "Bangumi search complete candidates=%s queries=%s",
            len(all_candidates),
            len(keywords),
        )
        return all_candidates[:_BGM_MAX_RESULTS]

    def enrich_candidate(
        self,
        query: MetadataSearchQuery,
        candidate: MetadataSearchCandidate,
    ) -> MetadataSearchCandidate:
        if self.content_extractor is None:
            return candidate
        try:
            return self.content_extractor.extract_from_candidate(
                query,
                candidate,
                book_id=query.book_id,
            )
        except Exception as exc:
            logger.warning("Bangumi AI extraction failed title=%s: %s", candidate.title, exc)
            return _candidate_with_extraction_failure(candidate, str(exc))

    def _fetch_subject_detail(
        self,
        subject_id: int,
        search_item: dict[str, Any],
    ) -> MetadataSearchCandidate | None:
        """Fetch subject details and build a candidate."""
        try:
            response = httpx.get(
                f"{self.base_url}/v0/subjects/{subject_id}",
                headers={
                    "User-Agent": self.user_agent,
                    "Accept": "application/json",
                },
                timeout=self.timeout_seconds,
                follow_redirects=True,
            )
            if response.status_code < 200 or response.status_code >= 300:
                logger.warning(
                    "Bangumi subject detail HTTP %s id=%s",
                    response.status_code,
                    subject_id,
                )
                # Fall back to search item data
                return self._build_candidate_from_search_item(search_item)

            detail = response.json()
        except Exception as exc:
            logger.warning(
                "Bangumi subject detail failed id=%s: %s",
                subject_id,
                exc,
            )
            return self._build_candidate_from_search_item(search_item)

        return self._build_candidate_from_detail(detail)

    def _build_candidate_from_search_item(
        self,
        item: dict[str, Any],
    ) -> MetadataSearchCandidate | None:
        """Build candidate from search item (fallback when detail fails)."""
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
        cover_url = str(
            images.get("large") or images.get("common") or images.get("medium") or ""
        )
        image_urls = _image_urls(images)

        summary = str(item.get("summary", "")).strip()
        raw_content_data = {
            "name": title,
            "name_cn": name_cn,
            "summary": summary,
            "images": images,
            "date": item.get("date", ""),
            "platform": item.get("platform", ""),
        }

        return MetadataSearchCandidate(
            title=display_title,
            original_title=title if title != display_title else "",
            summary=summary[:500],
            cover_url=cover_url,
            source_name="Bangumi",
            source_url=f"https://bgm.tv/subject/{subj_id}",
            source_type="community_database",
            verified=True,
            raw_content=json.dumps(raw_content_data, ensure_ascii=False)[:20000],
            raw_content_type="api_json",
            images=image_urls,
            extraction_status="not_extracted",
        )

    def _build_candidate_from_detail(
        self,
        detail: dict[str, Any],
    ) -> MetadataSearchCandidate:
        """Build candidate from subject detail API response."""
        subj_id = detail.get("id")
        title = str(detail.get("name", "")).strip()
        name_cn = str(detail.get("name_cn", "")).strip()

        if name_cn and name_cn != title:
            display_title = f"{title}（{name_cn}）"
        else:
            display_title = title or name_cn or ""

        images = detail.get("images") or {}
        cover_url = str(
            images.get("large") or images.get("common") or images.get("medium") or ""
        )
        image_urls = _image_urls(images)

        summary = str(detail.get("summary", "")).strip()

        # Extract tags
        tags = []
        for tag in detail.get("tags", [])[:10]:
            tag_name = tag.get("name")
            if tag_name:
                tags.append(str(tag_name))

        # Extract infobox data
        infobox = detail.get("infobox", [])
        authors: list[str] = []
        publisher = ""
        publication_date = ""

        for item in infobox:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key", "")).lower()
            value = item.get("value", "")

            if key in ["作者", "作者名", "原作"]:
                authors.extend(_extract_strings(value))
            elif key in ["出版社", "发行"]:
                publisher = _extract_first_string(value)
            elif key in ["发售日", "出版日期", "开始"]:
                publication_date = _extract_first_string(value)

        # Build raw content for AI extraction
        raw_content_data = {
            "name": title,
            "name_cn": name_cn,
            "summary": summary,
            "infobox": infobox[:20],  # Limit size
            "tags": tags,
            "images": images,
            "date": detail.get("date", ""),
            "platform": detail.get("platform", ""),
        }
        raw_content = json.dumps(raw_content_data, ensure_ascii=False)

        return MetadataSearchCandidate(
            title=display_title,
            original_title=title if title != display_title else "",
            authors=authors,
            publisher=publisher,
            publication_date=publication_date,
            summary=summary[:500],
            cover_url=cover_url,
            source_name="Bangumi",
            source_url=f"https://bgm.tv/subject/{subj_id}",
            source_type="community_database",
            genres=[],
            tags=tags,
            verified=True,
            raw_content=raw_content[:20000],
            raw_content_type="api_json",
            images=image_urls,
            extraction_status="not_extracted",
        )


def _build_keywords(query: MetadataSearchQuery) -> list[str]:
    """Build search keywords from query."""
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


def _extract_strings(value: Any) -> list[str]:
    """Extract strings from infobox value (can be string, list, or dict)."""
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        result = []
        for item in value:
            if isinstance(item, str):
                result.append(item.strip())
            elif isinstance(item, dict) and "v" in item:
                result.append(str(item["v"]).strip())
        return [s for s in result if s]
    return []


def _extract_first_string(value: Any) -> str:
    """Extract first string from infobox value."""
    strings = _extract_strings(value)
    return strings[0] if strings else ""


def _image_urls(images: Any) -> list[str]:
    if not isinstance(images, dict):
        return []
    urls: list[str] = []
    for key in ("large", "common", "medium", "small", "grid"):
        value = str(images.get(key) or "").strip()
        if value and value not in urls:
            urls.append(value)
    return urls


def _candidate_with_extraction_failure(candidate: MetadataSearchCandidate, error: str) -> MetadataSearchCandidate:
    return MetadataSearchCandidate(
        title=candidate.title,
        original_title=candidate.original_title,
        authors=candidate.authors,
        publisher=candidate.publisher,
        publication_date=candidate.publication_date,
        isbn=candidate.isbn,
        summary=candidate.summary,
        cover_url=candidate.cover_url,
        source_name=candidate.source_name,
        source_url=candidate.source_url,
        source_type=candidate.source_type,
        genres=candidate.genres,
        tags=candidate.tags,
        confidence=candidate.confidence,
        verified=candidate.verified,
        notes=candidate.notes,
        raw_content=candidate.raw_content,
        raw_content_type=candidate.raw_content_type,
        categories=candidate.categories,
        images=candidate.images,
        extraction_json=candidate.extraction_json,
        extraction_status="failed",
        extraction_error=error,
    )
