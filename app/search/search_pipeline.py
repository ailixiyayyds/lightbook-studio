from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from app.search.candidate_ranker import score_and_sort
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


def search_metadata_candidates(
    query: MetadataSearchQuery,
    *,
    max_candidates: int = 10,
) -> SearchResult:
    providers = _init_providers()
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

    return SearchResult(
        candidates=sorted_candidates[:max_candidates],
        diagnostics=all_diags,
    )


def _init_providers() -> list[BaseMetadataSearchProvider]:
    from app.search.providers.bangumi_provider import BangumiProvider
    from app.search.providers.google_books_provider import GoogleBooksProvider
    from app.search.providers.moegirl_provider import MoegirlProvider
    from app.search.providers.open_library_provider import OpenLibraryProvider
    from app.search.providers.other_providers import NdlSearchProvider

    return [
        BangumiProvider(timeout_seconds=10),
        MoegirlProvider(timeout_seconds=8),
        GoogleBooksProvider(timeout_seconds=10),
        NdlSearchProvider(timeout_seconds=10),
        OpenLibraryProvider(timeout_seconds=6),
    ]


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
