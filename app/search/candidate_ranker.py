from __future__ import annotations

import logging

from app.search.types import MetadataSearchCandidate, MetadataSearchQuery

logger = logging.getLogger(__name__)


def score_and_sort(
    query: MetadataSearchQuery,
    candidates: list[MetadataSearchCandidate],
) -> list[MetadataSearchCandidate]:
    """Score and sort candidates by relevance. Does NOT modify source_url or cover_url."""
    if not candidates:
        return []

    query_title = query.title.strip().lower()
    scored: list[tuple[int, MetadataSearchCandidate]] = []

    for c in candidates:
        score = _base_score(c, query_title)
        scored.append((score, c))

    scored.sort(key=lambda x: x[0])
    return [c for _, c in scored]


def _base_score(candidate: MetadataSearchCandidate, query_title: str) -> int:
    score = 0

    if candidate.verified:
        score -= 50

    source_prio = {
        "official_publisher": 0,
        "bookstore": 1,
        "library_metadata": 2,
        "community_database": 3,
        "search_result": 4,
        "manual": 5,
    }
    score += source_prio.get(candidate.source_type, 10) * 10

    if candidate.cover_url:
        score -= 5
    if candidate.summary:
        score -= 3
    if candidate.isbn:
        score -= 2
    if candidate.publisher:
        score -= 1

    match_assessment = candidate.extraction_json.get("match_assessment") if candidate.extraction_json else None
    if isinstance(match_assessment, dict) and match_assessment.get("is_likely_same_work") is False:
        score += 100

    c_title = candidate.title.lower()
    if query_title and query_title in c_title:
        score -= 10

    return score
