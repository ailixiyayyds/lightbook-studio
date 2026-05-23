from __future__ import annotations

import html as html_mod
import logging
import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None  # type: ignore[assignment,misc]

from app.search.provider import BaseMetadataSearchProvider
from app.search.types import MetadataSearchCandidate, MetadataSearchQuery

logger = logging.getLogger(__name__)

_TRUSTED_DOMAINS = [
    "bgm.tv", "bangumi.tv",
    "zh.moegirl.org.cn", "moegirl.org.cn",
    "zh.wikipedia.org", "en.wikipedia.org", "ja.wikipedia.org",
    "fandom.com",
    "anilist.co",
    "myanimelist.net",
    "mangaupdates.com",
    "mangadex.org",
    "book.douban.com", "douban.com",
]

_SEARCH_URL = "https://html.duckduckgo.com/html/"

_INVALID_IMAGE_KEYWORDS = [
    "logo", "icon", "favicon", "sprite", "avatar", "placeholder",
    "banner", "button", "pixel", "tracking", "ad.", "/ad/", "-ad-",
]

_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

_OG_TITLE_SELECTORS = [
    ("meta", {"property": "og:title"}),
    ("meta", {"name": "og:title"}),
]
_OG_IMAGE_SELECTORS = [
    ("meta", {"property": "og:image"}),
    ("meta", {"name": "og:image"}),
    ("link", {"rel": "image_src"}),
    ("meta", {"name": "twitter:image"}),
    ("meta", {"property": "twitter:image"}),
]
_OG_DESC_SELECTORS = [
    ("meta", {"property": "og:description"}),
    ("meta", {"name": "description"}),
    ("meta", {"name": "twitter:description"}),
    ("meta", {"property": "twitter:description"}),
]


class DuckDuckGoSearchProvider(BaseMetadataSearchProvider):
    name = "duckduckgo"

    def __init__(
        self,
        timeout_seconds: int = 15,
        max_candidates: int = 8,
        max_detail_pages: int = 3,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_candidates = max_candidates
        self.max_detail_pages = max_detail_pages

    def search(self, query: MetadataSearchQuery) -> list[MetadataSearchCandidate]:
        if BeautifulSoup is None:
            logger.error("缺少 beautifulsoup4，请安装 web 依赖：pip install beautifulsoup4 lxml")
            return []
        if not query.title.strip():
            return []

        search_terms = _build_search_terms(query)
        candidates: list[MetadataSearchCandidate] = []

        for terms in search_terms:
            if len(candidates) >= self.max_candidates:
                break
            try:
                urls = self._search_urls(terms)
                for url in urls:
                    if len(candidates) >= self.max_candidates:
                        break
                    if len(candidates) >= self.max_detail_pages:
                        candidate = self._candidate_from_search_snippet(url, terms)
                    else:
                        candidate = self._candidate_from_page(url, terms)
                    if candidate is not None:
                        candidates.append(candidate)
            except Exception:
                logger.exception("DuckDuckGo search failed for terms=%s", terms)
                continue

        candidates.sort(key=_trust_score, reverse=True)
        logger.info(
            "DuckDuckGo search done query=%s candidate_count=%s",
            query.title,
            len(candidates),
        )
        return candidates[: self.max_candidates]

    def _search_urls(self, query_str: str) -> list[str]:
        try:
            response = httpx.get(
                _SEARCH_URL,
                params={"q": query_str},
                headers={"User-Agent": _USER_AGENT},
                timeout=self.timeout_seconds,
                follow_redirects=True,
            )
            if response.status_code < 200 or response.status_code >= 300:
                raise RuntimeError(f"HTTP {response.status_code}")
        except httpx.TimeoutException as exc:
            logger.warning("DuckDuckGo search timeout query=%s", query_str)
            raise
        except httpx.HTTPError as exc:
            logger.warning("DuckDuckGo search HTTP error query=%s: %s", query_str, exc)
            raise

        return _extract_result_urls(response.text)

    def _candidate_from_page(self, url: str, fallback_title: str) -> MetadataSearchCandidate | None:
        try:
            response = httpx.get(
                url,
                headers={"User-Agent": _USER_AGENT},
                timeout=self.timeout_seconds,
                follow_redirects=True,
            )
            if response.status_code < 200 or response.status_code >= 300:
                logger.debug("Detail page returned status=%s url=%s", response.status_code, url)
                return None
        except Exception:
            logger.debug("Failed to fetch detail page url=%s", url)
            return None

        soup = BeautifulSoup(response.text, "html.parser")
        title = _extract_meta_content(soup, _OG_TITLE_SELECTORS) or _extract_html_title(soup) or fallback_title
        cover_url = _extract_cover_url(soup, url)
        summary = _extract_summary(soup)
        source_name = _source_display_name(url)

        return MetadataSearchCandidate(
            title=title,
            authors=[],
            summary=summary,
            cover_url=cover_url,
            source_name=source_name,
            source_url=url,
            tags=[],
            genres=[],
        )

    def _candidate_from_search_snippet(self, url: str, fallback_title: str) -> MetadataSearchCandidate | None:
        return MetadataSearchCandidate(
            title=fallback_title,
            summary="",
            cover_url="",
            source_name=_source_display_name(url),
            source_url=url,
        )


def _build_search_terms(query: MetadataSearchQuery) -> list[str]:
    title = query.title.strip()
    author = query.authors[0].strip() if query.authors else ""
    media_type = query.media_type or ""
    is_novel = media_type == "novel"

    terms_list: list[str] = []

    if author:
        lang = query.language_iso or ""
        if lang.startswith("en"):
            if is_novel:
                terms_list.append(f"{title} {author} light novel summary")
            else:
                terms_list.append(f"{title} {author} manga")
        else:
            if is_novel:
                terms_list.append(f"{title} {author} 轻小说 简介")
            else:
                terms_list.append(f"{title} {author} 漫画 简介")

    if is_novel:
        terms_list.append(f"{title} light novel")
    else:
        terms_list.append(f"{title} 漫画")

    if author and not any(author in t for t in terms_list):
        terms_list.insert(0, f"{title} {author}")

    return terms_list


def _extract_result_urls(html_text: str) -> list[str]:
    if BeautifulSoup is None:
        return []
    urls: list[str] = []
    seen: set[str] = set()
    soup = BeautifulSoup(html_text, "html.parser")

    for link in soup.select("a.result__a"):
        href = link.get("href")
        if not href or not isinstance(href, str):
            continue
        if href.startswith("//"):
            href = "https:" + href
        parsed = urlparse(href)
        if not parsed.scheme or not parsed.netloc:
            continue
        if href not in seen:
            seen.add(href)
            urls.append(href)

    return urls


def _extract_meta_content(soup: BeautifulSoup, selectors: list[tuple[str, dict[str, str]]]) -> str | None:
    for tag_name, attrs in selectors:
        element = soup.find(tag_name, attrs)
        if element:
            content = element.get("content", "")
            if content and isinstance(content, str) and content.strip():
                return content.strip()
    return None


def _extract_html_title(soup: BeautifulSoup) -> str:
    title_tag = soup.find("title")
    if title_tag and title_tag.string:
        text = title_tag.string.strip()
        separators = [" - ", " | ", " – ", " — ", " · "]
        for sep in separators:
            if sep in text:
                parts = text.split(sep)
                longest = max(parts, key=len).strip()
                if len(longest) > 3:
                    return longest
        return text
    return ""


def _extract_cover_url(soup: BeautifulSoup, page_url: str) -> str:
    raw = _extract_meta_content(soup, _OG_IMAGE_SELECTORS)
    if not raw:
        return ""

    candidate = urljoin(page_url, raw)
    parsed = urlparse(candidate)
    if parsed.scheme not in ("http", "https"):
        return ""

    path_lower = parsed.path.lower()
    if not any(path_lower.endswith(ext) for ext in _IMAGE_EXTENSIONS):
        return ""

    for keyword in _INVALID_IMAGE_KEYWORDS:
        if keyword in path_lower:
            return ""

    return candidate


def _extract_summary(soup: BeautifulSoup) -> str:
    raw = _extract_meta_content(soup, _OG_DESC_SELECTORS)
    if not raw:
        return ""

    text = _strip_html(raw)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > 500:
        text = text[:497] + "..."
    return text


def _strip_html(value: str) -> str:
    class _Stripper(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.parts: list[str] = []

        def handle_data(self, data: str) -> None:
            self.parts.append(data)

    stripper = _Stripper()
    stripper.feed(value)
    return "".join(stripper.parts)


def _source_display_name(url: str) -> str:
    parsed = urlparse(url)
    netloc = parsed.netloc.lower()

    domain_map: dict[str, str] = {
        "bgm.tv": "Bangumi",
        "bangumi.tv": "Bangumi",
        "zh.moegirl.org.cn": "萌娘百科",
        "moegirl.org.cn": "萌娘百科",
        "zh.wikipedia.org": "维基百科",
        "en.wikipedia.org": "Wikipedia",
        "ja.wikipedia.org": "Wikipedia",
        "fandom.com": "Fandom",
        "anilist.co": "AniList",
        "myanimelist.net": "MyAnimeList",
        "mangaupdates.com": "MangaUpdates",
        "mangadex.org": "MangaDex",
        "book.douban.com": "豆瓣读书",
        "douban.com": "豆瓣",
    }

    for domain, name in domain_map.items():
        if domain in netloc:
            return name

    return netloc.split(":")[0].removeprefix("www.")


def _trust_score(candidate: MetadataSearchCandidate) -> int:
    url_lower = candidate.source_url.lower()
    for domain in _TRUSTED_DOMAINS:
        if domain in url_lower:
            return 0
    has_cover = 1 if candidate.cover_url else 0
    has_summary = 1 if candidate.summary else 0
    return 100 - has_cover - has_summary
