from __future__ import annotations

from app.search.types import is_valid_search_title


class TestIsValidSearchTitle:

    def test_rejects_pure_numbers(self) -> None:
        assert is_valid_search_title("3159") is False
        assert is_valid_search_title("123456") is False

    def test_rejects_numeric_with_encoding(self) -> None:
        assert is_valid_search_title("3159 gbk") is False
        assert is_valid_search_title("123456 utf8") is False
        assert is_valid_search_title("139089 utf-8") is False

    def test_rejects_numeric_with_extension(self) -> None:
        assert is_valid_search_title("3159.txt") is False
        assert is_valid_search_title("123456 .epub") is False

    def test_accepts_real_titles(self) -> None:
        assert is_valid_search_title("灰原同学重返过去") is True
        assert is_valid_search_title("葬送のフリーレン") is True
        assert is_valid_search_title("Frieren Beyond Journey's End") is True
        assert is_valid_search_title("Berserk") is True

    def test_rejects_empty(self) -> None:
        assert is_valid_search_title("") is False
        assert is_valid_search_title("   ") is False
