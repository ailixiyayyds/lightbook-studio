"""MediaWiki category filtering utilities."""

from __future__ import annotations

import re

# Patterns that indicate maintenance/administrative categories
_MAINTENANCE_PATTERNS = [
    re.compile(r"页面"),
    re.compile(r"模板"),
    re.compile(r"帮助"),
    re.compile(r"维护"),
    re.compile(r"需要"),
    re.compile(r"缺少"),
    re.compile(r"消歧义"),
    re.compile(r"分类"),
    re.compile(r"带有"),
    re.compile(r"使用"),
    re.compile(r"含有"),
    re.compile(r"可能"),
    re.compile(r"条目$"),
    re.compile(r"^Category:"),
    re.compile(r"^分类:"),
]

# Patterns for useful content categories
_USEFUL_PATTERNS = [
    re.compile(r"漫画"),
    re.compile(r"轻小说"),
    re.compile(r"百合"),
    re.compile(r"校园"),
    re.compile(r"恋爱"),
    re.compile(r"动画"),
    re.compile(r"游戏"),
    re.compile(r"角色"),
    re.compile(r"作品"),
    re.compile(r"出版社"),
    re.compile(r"作者"),
    re.compile(r"奇幻"),
    re.compile(r"科幻"),
    re.compile(r"悬疑"),
    re.compile(r"冒险"),
    re.compile(r"日常"),
    re.compile(r"喜剧"),
    re.compile(r"治愈"),
    re.compile(r"青春"),
]


def clean_mediawiki_categories(categories: list[str]) -> list[str]:
    """Filter out maintenance categories from MediaWiki category list.

    Args:
        categories: Raw category list from MediaWiki API.

    Returns:
        Filtered list with maintenance categories removed.
    """
    if not categories:
        return []

    cleaned: list[str] = []
    for cat in categories:
        if not cat or not isinstance(cat, str):
            continue

        cat_stripped = cat.strip()
        if not cat_stripped:
            continue

        # Skip maintenance categories
        is_maintenance = False
        for pattern in _MAINTENANCE_PATTERNS:
            if pattern.search(cat_stripped):
                is_maintenance = True
                break

        if is_maintenance:
            continue

        cleaned.append(cat_stripped)

    return cleaned


def filter_useful_categories(categories: list[str]) -> list[str]:
    """Extract only categories that look like content-related.

    This is more aggressive than clean_mediawiki_categories and only
    keeps categories that match known useful patterns.

    Args:
        categories: Category list (preferably already cleaned).

    Returns:
        List of categories that match useful content patterns.
    """
    if not categories:
        return []

    useful: list[str] = []
    for cat in categories:
        if not cat or not isinstance(cat, str):
            continue

        cat_stripped = cat.strip()
        if not cat_stripped:
            continue

        for pattern in _USEFUL_PATTERNS:
            if pattern.search(cat_stripped):
                useful.append(cat_stripped)
                break

    return useful
