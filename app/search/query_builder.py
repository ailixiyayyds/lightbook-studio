from __future__ import annotations

from app.search.types import MetadataSearchQuery


class SearchQueryPlan:
    def __init__(
        self,
        normalized_title: str,
        author_terms: list[str],
        jp_queries: list[str],
        en_queries: list[str],
        bookstore_queries: list[str],
        official_queries: list[str],
    ) -> None:
        self.normalized_title = normalized_title
        self.author_terms = author_terms
        self.jp_queries = jp_queries
        self.en_queries = en_queries
        self.bookstore_queries = bookstore_queries
        self.official_queries = official_queries

    def all_queries(self) -> list[str]:
        queries: list[str] = []
        queries.extend(self.jp_queries)
        queries.extend(self.en_queries)
        queries.extend(self.official_queries)
        queries.extend(self.bookstore_queries)
        if not queries:
            queries.append(self.normalized_title)
        return queries


def build_query_plan(query: MetadataSearchQuery) -> SearchQueryPlan:
    title = query.title.strip()
    clean = query.local_clean_title.strip() or title
    authors = [a.strip() for a in query.authors if a.strip()]
    author_str = " ".join(authors)

    jp_queries: list[str] = []
    en_queries: list[str] = []
    bookstore_queries: list[str] = []
    official_queries: list[str] = []

    if query.language_iso.startswith("ja") or _has_japanese(title):
        jp_queries.append(f"{title} 漫画")
        if author_str:
            jp_queries.append(f"{title} {author_str}")
        official_queries.append(f"{title} 出版社")
    elif query.language_iso.startswith("en"):
        en_queries.append(f"{title} manga")
        if author_str:
            en_queries.append(f"{title} {author_str}")
    else:
        jp_queries.append(f"{title} 漫画")
        en_queries.append(f"{title} manga")
        if author_str:
            jp_queries.append(f"{title} {author_str}")
            en_queries.append(f"{title} {author_str}")

    if query.original_title.strip() and query.original_title.strip() != title:
        orig = query.original_title.strip()
        jp_queries.append(f"{orig} 漫画")
        if author_str:
            jp_queries.append(f"{orig} {author_str}")
        bookstore_queries.append(f"{orig} Amazon")
        official_queries.append(f"{orig} 出版社")

    if clean != title:
        jp_queries.insert(0, f"{clean} 漫画")

    if not jp_queries and not en_queries:
        jp_queries.append(f"{title}")

    return SearchQueryPlan(
        normalized_title=clean or title,
        author_terms=authors,
        jp_queries=jp_queries[:3],
        en_queries=en_queries[:3],
        bookstore_queries=bookstore_queries[:3],
        official_queries=official_queries[:3],
    )


def _has_japanese(text: str) -> bool:
    for ch in text:
        cp = ord(ch)
        if 0x3040 <= cp <= 0x309F or 0x30A0 <= cp <= 0x30FF or 0x4E00 <= cp <= 0x9FFF:
            return True
    return False
