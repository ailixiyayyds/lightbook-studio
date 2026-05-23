"""Metadata search pipeline that coordinates multiple providers.

This module provides the main search functionality that:
1. Queries multiple metadata providers
2. Deduplicates and scores results
3. Optionally runs AI content extraction on candidates
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.search.candidate_ranker import score_and_sort
from app.search.config import SearchConfig
from app.search.provider import BaseMetadataSearchProvider
from app.search.types import MetadataSearchCandidate, MetadataSearchQuery

logger = logging.getLogger(__name__)

_GOOGLE_BOOKS_COOLDOWN = 600  # 10 minutes
_last_google_429: float = 0


@dataclass
class ProviderDiagnostic:
    name: str = ""
    enabled: bool = True
    query_count: int = 0
    candidate_count: int = 0
    error: str | None = None


@dataclass
class SearchResult:
    candidates: list[MetadataSearchCandidate] = field(default_factory=list)
    diagnostics: list[ProviderDiagnostic] = field(default_factory=list)


class ContentExtractorProtocol(Protocol):
    """Protocol for content extractor."""

    def extract_from_candidate(
        self,
        query: MetadataSearchQuery,
        candidate: MetadataSearchCandidate,
        *,
        book_id: int | None = None,
    ) -> MetadataSearchCandidate:
        """Extract metadata from candidate's raw content."""
        ...


def search_metadata_candidates(
    query: MetadataSearchQuery,
    *,
    max_candidates: int = 10,
    content_extractor: ContentExtractorProtocol | None = None,
    book_id: int | None = None,
    search_config: SearchConfig | None = None,
) -> SearchResult:
    """Search for metadata candidates from multiple providers.

    Args:
        query: The search query.
        max_candidates: Maximum number of candidates to return.
        content_extractor: Optional content extractor for AI extraction.
            If provided, it is passed to providers that support enrichment
            (Moegirl, Bangumi) so they can run extraction during search.
        book_id: Optional book ID for logging.

    Returns:
        SearchResult with candidates and diagnostics.
    """
    if search_config is not None and not search_config.enabled:
        return SearchResult(
            candidates=[],
            diagnostics=[
                ProviderDiagnostic(
                    name="metadata_search",
                    enabled=False,
                    error="资料搜索已在设置中禁用",
                )
            ],
        )

    providers = _init_providers(content_extractor=content_extractor, config=search_config)
    all_diags: list[ProviderDiagnostic] = []
    all_candidates: list[MetadataSearchCandidate] = []

    for provider in providers:
        name = getattr(provider, "name", provider.__class__.__name__)
        diag = ProviderDiagnostic(name=name, enabled=True)

        # Google Books cooldown
        if name == "google_books":
            global _last_google_429
            if time.time() - _last_google_429 < _GOOGLE_BOOKS_COOLDOWN:
                remaining = int(_GOOGLE_BOOKS_COOLDOWN - (time.time() - _last_google_429))
                diag.error = f"Google Books skipped: rate limited, cooldown {remaining}s remaining"
                diag.enabled = False
                all_diags.append(diag)
                continue

        try:
            result = provider.search(query)
            diag.candidate_count = len(result)
            all_candidates.extend(result)
            if hasattr(provider, "last_error") and provider.last_error:
                diag.error = provider.last_error
                if "429" in str(provider.last_error):
                    _last_google_429 = time.time()
            logger.info("Provider %s: %s candidates", name, len(result))
        except Exception as exc:
            diag.error = str(exc)
            logger.warning("Provider %s failed: %s", name, exc)

        all_diags.append(diag)

    deduped = _deduplicate(all_candidates)
    sorted_candidates = score_and_sort(query, deduped)

    # Run AI content extraction on candidates from providers that don't
    # handle extraction themselves (Google Books, Open Library, etc.)
    if content_extractor is not None:
        extract_limit = search_config.content_extract_top_n if search_config is not None else None
        sorted_candidates = _run_content_extraction(
            query,
            sorted_candidates,
            content_extractor,
            book_id=book_id,
            max_extractions=extract_limit,
        )
        sorted_candidates = score_and_sort(query, sorted_candidates)

    return SearchResult(
        candidates=sorted_candidates[:max_candidates],
        diagnostics=all_diags,
    )


def _run_content_extraction(
    query: MetadataSearchQuery,
    candidates: list[MetadataSearchCandidate],
    extractor: ContentExtractorProtocol,
    *,
    book_id: int | None = None,
    max_extractions: int | None = None,
) -> list[MetadataSearchCandidate]:
    """Run AI content extraction on candidates with raw content.

    Only extracts candidates that have raw_content and haven't been
    extracted yet (extraction_status == "not_extracted"). Candidates
    already extracted by their provider (extraction_status != "not_extracted")
    are skipped to avoid double extraction.
    """
    extracted: list[MetadataSearchCandidate] = []
    extraction_count = 0

    for candidate in candidates:
        should_extract = candidate.raw_content and candidate.extraction_status == "not_extracted"
        if should_extract and max_extractions is not None and extraction_count >= max_extractions:
            extracted.append(candidate)
            continue

        if should_extract:
            try:
                logger.debug(
                    "Running content extraction for candidate title=%s source=%s",
                    candidate.title,
                    candidate.source_name,
                )
                updated = extractor.extract_from_candidate(
                    query,
                    candidate,
                    book_id=book_id,
                )
                extraction_count += 1
                extracted.append(updated)
            except Exception as exc:
                logger.warning(
                    "Content extraction failed for candidate title=%s: %s",
                    candidate.title,
                    exc,
                )
                # Keep original candidate with failed status
                extracted.append(
                    MetadataSearchCandidate(
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
                        extraction_json={},
                        extraction_status="failed",
                        extraction_error=str(exc),
                    )
                )
                extraction_count += 1
        else:
            extracted.append(candidate)

    return extracted


def _init_providers(
    content_extractor: ContentExtractorProtocol | None = None,
    config: SearchConfig | None = None,
) -> list[BaseMetadataSearchProvider]:
    from app.search.providers.bangumi_provider import BangumiProvider
    from app.search.providers.google_books_provider import GoogleBooksProvider
    from app.search.providers.moegirl_provider import MoegirlProvider
    from app.search.providers.open_library_provider import OpenLibraryProvider
    from app.search.providers.other_providers import GenericSearchProvider, NdlSearchProvider

    cfg = config or SearchConfig()
    providers: list[BaseMetadataSearchProvider] = []
    if cfg.bangumi_enabled:
        providers.append(
            BangumiProvider(
                timeout_seconds=cfg.bangumi_timeout_seconds,
                content_extractor=content_extractor,
                base_url=cfg.bangumi_base_url,
                user_agent=cfg.bangumi_user_agent,
                max_queries=cfg.bangumi_max_queries,
            )
        )
    if cfg.moegirl_enabled:
        providers.append(
            MoegirlProvider(
                timeout_seconds=cfg.moegirl_timeout_seconds,
                content_extractor=content_extractor,
                api_url=cfg.moegirl_api_url,
                user_agent=cfg.moegirl_user_agent,
                parse_api_enabled=cfg.moegirl_parse_api_enabled,
                wikitext_fallback_enabled=cfg.moegirl_wikitext_fallback_enabled,
                html_fallback_enabled=cfg.moegirl_html_fallback_enabled,
                max_detail_pages=cfg.moegirl_max_detail_pages,
            )
        )
    if cfg.google_books_enabled:
        providers.append(
            GoogleBooksProvider(
                timeout_seconds=cfg.google_books_timeout_seconds,
                api_key_env=cfg.google_books_api_key_env,
            )
        )
    if cfg.ndl_enabled:
        providers.append(
            NdlSearchProvider(
                timeout_seconds=cfg.ndl_timeout_seconds,
                base_url=cfg.ndl_base_url,
            )
        )
    if cfg.open_library_enabled:
        providers.append(
            OpenLibraryProvider(
                timeout_seconds=cfg.open_library_timeout_seconds,
                base_url=cfg.open_library_base_url,
            )
        )
    if cfg.generic_search_provider.strip().casefold() != "disabled":
        providers.append(
            GenericSearchProvider(
                enabled=True,
                provider_type=cfg.generic_search_provider,
                endpoint=cfg.generic_search_endpoint,
                api_key_env=cfg.generic_search_api_key_env,
            )
        )
    return providers


def _deduplicate(candidates: list[MetadataSearchCandidate]) -> list[MetadataSearchCandidate]:
    seen_urls: set[str] = set()
    seen_isbns: set[str] = set()
    result: list[MetadataSearchCandidate] = []

    for c in candidates:
        url_key = c.source_url.strip().lower()
        if url_key and url_key in seen_urls:
            continue
        if url_key:
            seen_urls.add(url_key)

        isbn = c.isbn.strip()
        if isbn and isbn in seen_isbns:
            continue
        if isbn:
            seen_isbns.add(isbn)

        result.append(c)

    return result
