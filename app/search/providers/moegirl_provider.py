"""Moegirl (萌娘百科) metadata search provider.

Uses MediaWiki Action API to search and fetch page content.
Never scrapes HTML pages - all requests go through the API.

API endpoint: https://zh.moegirl.org.cn/api.php

Search: action=opensearch or action=query&list=search
Details: action=query&prop=extracts|pageimages|info|categories
Fallback: action=parse for wikitext/html when extracts are insufficient
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx

from app.search.mediawiki_utils import clean_mediawiki_categories
from app.search.provider import BaseMetadataSearchProvider
from app.search.types import MetadataSearchCandidate, MetadataSearchQuery, is_valid_search_title

logger = logging.getLogger(__name__)

_MOEGIRL_API = "https://zh.moegirl.org.cn/api.php"
_USER_AGENT = "LightBookStudio/0.4"
_MAX_RESULTS = 8
_MAX_QUERIES = 12
_MAX_DETAIL_PER_QUERY = 3
_TIMEOUT_SECONDS = 8

# Minimum extract length to consider sufficient
_MIN_EXTRACT_LENGTH = 200


@dataclass(frozen=True)
class _ParseDetail:
    raw_content: str = ""
    raw_content_type: str = ""
    categories: list[str] = field(default_factory=list)
    images: list[str] = field(default_factory=list)
    html_fallback_used: bool = False


class MoegirlProvider(BaseMetadataSearchProvider):
    """Metadata search provider for 萌娘百科 using MediaWiki API."""

    name = "moegirl"

    def __init__(
        self,
        timeout_seconds: int = _TIMEOUT_SECONDS,
        content_extractor: Any | None = None,
        api_url: str = _MOEGIRL_API,
        user_agent: str = _USER_AGENT,
        parse_api_enabled: bool = True,
        wikitext_fallback_enabled: bool = True,
        html_fallback_enabled: bool = False,
        max_detail_pages: int = _MAX_DETAIL_PER_QUERY,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.content_extractor = content_extractor
        self.api_url = api_url
        self.user_agent = user_agent or _USER_AGENT
        self.parse_api_enabled = parse_api_enabled
        self.wikitext_fallback_enabled = wikitext_fallback_enabled
        self.html_fallback_enabled = html_fallback_enabled
        self.max_detail_pages = max(1, max_detail_pages)
        self._error: str | None = None

    @property
    def last_error(self) -> str | None:
        return self._error

    def search(self, query: MetadataSearchQuery) -> list[MetadataSearchCandidate]:
        """Search for metadata candidates from 萌娘百科."""
        self._error = None
        keywords = _build_keywords(query)
        titles_found: set[str] = set()
        candidates: list[MetadataSearchCandidate] = []

        logger.info(
            "Moegirl search start keywords=%s title=%s",
            len(keywords),
            query.title,
        )

        # Step 1: Search for page titles
        for kw in keywords[:_MAX_QUERIES]:
            page_titles = self._search_titles(kw)
            for pt in page_titles:
                if pt not in titles_found:
                    titles_found.add(pt)

            if len(titles_found) >= _MAX_RESULTS * 2:
                break

        # Step 2: Fetch details for each title
        for pt in list(titles_found)[: min(_MAX_RESULTS * 2, self.max_detail_pages * _MAX_QUERIES)]:
            c = self._fetch_page_details(pt)
            if c is not None:
                candidates.append(self.enrich_candidate(query, c))

            if len(candidates) >= _MAX_RESULTS:
                break

        logger.info(
            "Moegirl search complete candidates=%s titles_found=%s",
            len(candidates),
            len(titles_found),
        )
        return candidates

    def _search_titles(self, keyword: str) -> list[str]:
        """Search for page titles using opensearch API."""
        try:
            response = httpx.get(
                self.api_url,
                params={
                    "action": "opensearch",
                    "search": keyword,
                    "limit": "10",
                    "namespace": "0",
                    "format": "json",
                },
                headers={"User-Agent": self.user_agent},
                timeout=self.timeout_seconds,
                follow_redirects=True,
            )
            if response.status_code < 200 or response.status_code >= 300:
                logger.warning(
                    "Moegirl opensearch HTTP %s keyword=%s",
                    response.status_code,
                    keyword,
                )
                return []
            data = response.json()
            # opensearch returns [query, [titles], [descriptions], [urls]]
            if len(data) > 1 and isinstance(data[1], list):
                return [str(t) for t in data[1] if isinstance(t, str)]
            return []
        except Exception as exc:
            logger.warning("Moegirl opensearch failed keyword=%s: %s", keyword, exc)
            return []

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
            logger.warning("Moegirl AI extraction failed title=%s: %s", candidate.title, exc)
            return _candidate_with_extraction_failure(candidate, str(exc))

    def _fetch_page_details(self, title: str) -> MetadataSearchCandidate | None:
        """Fetch page details using query API."""
        try:
            # First try query API with extracts, pageimages, info, categories
            response = httpx.get(
                self.api_url,
                params={
                    "action": "query",
                    "prop": "info|pageimages|categories",
                    "titles": title,
                    "piprop": "original|thumbnail|name",
                    "pithumbsize": "300",
                    "inprop": "url",
                    "cllimit": "50",
                    "format": "json",
                },
                headers={"User-Agent": self.user_agent},
                timeout=self.timeout_seconds,
                follow_redirects=True,
            )
            if response.status_code < 200 or response.status_code >= 300:
                logger.warning(
                    "Moegirl query HTTP %s title=%s",
                    response.status_code,
                    title,
                )
                return None

            data = response.json()
        except Exception as exc:
            logger.warning("Moegirl query failed title=%s: %s", title, exc)
            return None

        pages = data.get("query", {}).get("pages", {})
        for page_id, page in pages.items():
            if int(page_id) < 0:
                continue

            page_title = str(page.get("title", "")).strip()
            if _is_disambiguation(page_title):
                continue

            # Extract data from query response
            fullurl = str(page.get("fullurl", ""))

            # Get categories
            categories_raw = page.get("categories", [])
            categories = [
                str(cat.get("title", "")).replace("Category:", "").replace("分类:", "")
                for cat in categories_raw
                if isinstance(cat, dict)
            ]
            categories = clean_mediawiki_categories(categories)

            # Get page images
            images: list[str] = []
            original = page.get("original", {})
            if isinstance(original, dict) and original.get("source"):
                images.append(str(original["source"]))
            thumbnail = page.get("thumbnail", {})
            if isinstance(thumbnail, dict) and thumbnail.get("source"):
                thumb_url = str(thumbnail["source"])
                if thumb_url not in images:
                    images.append(thumb_url)

            cover_url = images[0] if images else ""

            # Check if extract is sufficient
            extract = str(page.get("extract", "")).strip() or self._fetch_extract(title)
            raw_content = extract
            raw_content_type = "extract"

            # If extract is too short, try parse API for more content
            if self.parse_api_enabled and len(extract) < _MIN_EXTRACT_LENGTH:
                parse_detail = self._fetch_parse_content(title)
                if parse_detail.raw_content:
                    raw_content = parse_detail.raw_content
                    raw_content_type = parse_detail.raw_content_type
                    categories = clean_mediawiki_categories([*categories, *parse_detail.categories])
                    for image in parse_detail.images:
                        if image not in images:
                            images.append(image)
            source_url = fullurl or f"https://zh.moegirl.org.cn/{page_title}"
            html_fallback_used = False
            if self.html_fallback_enabled and len(raw_content) < _MIN_EXTRACT_LENGTH:
                html_detail = self._fetch_html_fallback(source_url)
                if html_detail.raw_content:
                    raw_content = html_detail.raw_content
                    raw_content_type = html_detail.raw_content_type
                    html_fallback_used = True

            # Truncate raw_content for storage
            raw_content_truncated = raw_content[:20000]

            return MetadataSearchCandidate(
                title=page_title,
                summary="",  # Will be filled by AI extraction
                cover_url=cover_url,
                source_name="萌娘百科",
                source_url=source_url,
                source_type="community_database",
                verified=True,
                raw_content=raw_content_truncated,
                raw_content_type=raw_content_type,
                categories=categories,
                images=images,
                notes=["html_fallback_used"] if html_fallback_used else [],
                extraction_status="not_extracted",
            )

        return None

    def _fetch_extract(self, title: str) -> str:
        try:
            response = httpx.get(
                self.api_url,
                params={
                    "action": "query",
                    "prop": "extracts",
                    "titles": title,
                    "exintro": "0",
                    "explaintext": "1",
                    "format": "json",
                },
                headers={"User-Agent": self.user_agent},
                timeout=self.timeout_seconds,
                follow_redirects=True,
            )
            if response.status_code < 200 or response.status_code >= 300:
                return ""
            pages = response.json().get("query", {}).get("pages", {})
            for page in pages.values():
                if isinstance(page, dict):
                    return str(page.get("extract", "")).strip()
        except Exception as exc:
            logger.debug("Moegirl extracts API failed title=%s: %s", title, exc)
        return ""

    def _fetch_parse_content(self, title: str) -> "_ParseDetail":
        """Fetch page content using parse API as fallback."""
        detail = self._fetch_parse_prop(title, "text|categories|images|displaytitle|externallinks|links")
        if detail.raw_content and len(detail.raw_content) > _MIN_EXTRACT_LENGTH:
            return detail
        if self.wikitext_fallback_enabled:
            wiki_detail = self._fetch_parse_prop(title, "wikitext|categories|images|displaytitle")
            if wiki_detail.raw_content:
                return wiki_detail
        return detail

    def _fetch_parse_prop(self, title: str, prop: str) -> "_ParseDetail":
        try:
            response = httpx.get(
                self.api_url,
                params={
                    "action": "parse",
                    "page": title,
                    "prop": prop,
                    "warnings": "1",
                    "format": "json",
                    "formatversion": "2",
                },
                headers={"User-Agent": self.user_agent},
                timeout=self.timeout_seconds,
                follow_redirects=True,
            )
            if response.status_code < 200 or response.status_code >= 300:
                return _ParseDetail()
            parse_result = response.json().get("parse", {})
            categories = _parse_categories(parse_result.get("categories", []))
            images = _parse_images(parse_result.get("images", []))
            if "wikitext" in prop:
                raw = parse_result.get("wikitext", "")
                if isinstance(raw, str):
                    return _ParseDetail(
                        raw_content=raw[:20000],
                        raw_content_type="wikitext",
                        categories=categories,
                        images=images,
                    )
            html_text = parse_result.get("text", "")
            if isinstance(html_text, str) and html_text:
                return _ParseDetail(
                    raw_content=_clean_html_text(html_text)[:20000],
                    raw_content_type="html",
                    categories=categories,
                    images=images,
                )
        except Exception as exc:
            logger.debug("Moegirl parse API failed title=%s: %s", title, exc)
        return _ParseDetail()

    def _fetch_html_fallback(self, source_url: str) -> "_ParseDetail":
        parsed = urlparse(source_url)
        if parsed.hostname != "zh.moegirl.org.cn":
            return _ParseDetail()
        try:
            response = httpx.get(
                source_url,
                headers={"User-Agent": self.user_agent},
                timeout=self.timeout_seconds,
                follow_redirects=True,
            )
            if response.status_code < 200 or response.status_code >= 300:
                return _ParseDetail()
            return _ParseDetail(
                raw_content=_clean_html_text(response.text)[:40000],
                raw_content_type="html_fallback",
                html_fallback_used=True,
            )
        except Exception as exc:
            logger.debug("Moegirl HTML fallback failed url=%s: %s", source_url, exc)
            return _ParseDetail()


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

    # Add author combinations
    for author in query.authors[:2]:
        for t in [query.local_clean_title, query.title]:
            if t.strip():
                add(f"{t} {author}")

    return keywords[:_MAX_QUERIES]


def _is_disambiguation(title: str) -> bool:
    """Check if title is a disambiguation page."""
    return "消歧义" in title or " (消歧义)" in title or "（消歧义）" in title


def _parse_categories(raw: Any) -> list[str]:
    categories: list[str] = []
    if not isinstance(raw, list):
        return categories
    for item in raw:
        if isinstance(item, str):
            text = item
        elif isinstance(item, dict):
            text = str(item.get("category") or item.get("title") or "")
        else:
            continue
        text = text.replace("Category:", "").replace("分类:", "").strip()
        if text:
            categories.append(text)
    return clean_mediawiki_categories(categories)


def _parse_images(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    images: list[str] = []
    for item in raw:
        if isinstance(item, str):
            text = item.strip()
        elif isinstance(item, dict):
            text = str(item.get("name") or item.get("title") or "").strip()
        else:
            continue
        if text:
            images.append(text)
    return images


def _clean_html_text(html: str) -> str:
    text = re.sub(r"(?is)<(script|style|nav|header|footer)[^>]*>.*?</\1>", " ", html)
    text = re.sub(r"(?is)<(sup|tableofcontents|aside)[^>]*>.*?</\1>", " ", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|tr|li|h[1-6])>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
    )
    return re.sub(r"\s+", " ", text).strip()


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
