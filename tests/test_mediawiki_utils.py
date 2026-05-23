"""Tests for MediaWiki category filtering utilities."""

import pytest

from app.search.mediawiki_utils import clean_mediawiki_categories, filter_useful_categories


class TestCleanMediawikiCategories:
    def test_empty_input(self) -> None:
        assert clean_mediawiki_categories([]) == []
        assert clean_mediawiki_categories(None) == []  # type: ignore

    def test_filter_maintenance_categories(self) -> None:
        categories = [
            "需要参考资料",
            "缺少封面",
            "维护分类",
            "消歧义页面",
            "模板文档",
            "帮助文档",
            "带有过期参数的页面",
            "使用未知参数的页面",
        ]
        assert clean_mediawiki_categories(categories) == []

    def test_keep_useful_categories(self) -> None:
        categories = [
            "漫画作品",
            "轻小说",
            "百合漫画",
            "校园题材",
            "恋爱漫画",
        ]
        result = clean_mediawiki_categories(categories)
        assert len(result) == 5

    def test_mixed_categories(self) -> None:
        categories = [
            "漫画作品",
            "需要参考资料",
            "百合漫画",
            "维护分类",
            "校园题材",
        ]
        result = clean_mediawiki_categories(categories)
        assert "漫画作品" in result
        assert "百合漫画" in result
        assert "校园题材" in result
        assert "需要参考资料" not in result
        assert "维护分类" not in result

    def test_strip_whitespace(self) -> None:
        categories = ["  漫画作品  ", "\t轻小说\t", "\n百合\n"]
        result = clean_mediawiki_categories(categories)
        assert result == ["漫画作品", "轻小说", "百合"]

    def test_skip_empty_strings(self) -> None:
        categories = ["漫画作品", "", "  ", "\t", "轻小说"]
        result = clean_mediawiki_categories(categories)
        assert result == ["漫画作品", "轻小说"]

    def test_category_prefix_filtered(self) -> None:
        categories = [
            "Category:漫画作品",
            "分类:轻小说",
            "漫画作品",
        ]
        result = clean_mediawiki_categories(categories)
        assert "漫画作品" in result
        assert "Category:漫画作品" not in result
        assert "分类:轻小说" not in result


class TestFilterUsefulCategories:
    def test_empty_input(self) -> None:
        assert filter_useful_categories([]) == []

    def test_only_useful_kept(self) -> None:
        categories = [
            "漫画作品",
            "某个普通分类",  # Not matching any useful pattern
            "百合漫画",
            "出版社",
        ]
        result = filter_useful_categories(categories)
        assert "漫画作品" in result
        assert "百合漫画" in result
        assert "出版社" in result
        assert "某个普通分类" not in result

    def test_all_useful(self) -> None:
        categories = [
            "漫画",
            "轻小说",
            "百合",
            "校园",
            "恋爱",
            "动画",
            "游戏",
            "角色",
            "作品",
            "出版社",
            "作者",
            "奇幻",
            "科幻",
            "悬疑",
            "冒险",
            "日常",
            "喜剧",
            "治愈",
            "青春",
        ]
        result = filter_useful_categories(categories)
        assert len(result) == 19

    def test_non_useful_filtered(self) -> None:
        categories = [
            "某个无关分类",
            "杂志连载",
            "网站导航",
        ]
        result = filter_useful_categories(categories)
        assert result == []
