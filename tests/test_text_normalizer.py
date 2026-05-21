from __future__ import annotations

from app.utils.text_normalizer import normalize_cjk_title


class TestNormalizeCjkTitle:

    def test_strips_punctuation(self) -> None:
        assert normalize_cjk_title("轻小说，标题！") == "轻小说标题"

    def test_strips_brackets(self) -> None:
        assert normalize_cjk_title("《测试》作品") == "测试作品"

    def test_strips_volume(self) -> None:
        result = normalize_cjk_title("测试作品 第01卷")
        assert "第01卷" not in result
        assert "测试作品" in result

    def test_strips_release_tags(self) -> None:
        assert "[Kome]" not in normalize_cjk_title("[Kome]测试作品")

    def test_normalizes_simplified_to_traditional(self) -> None:
        result = normalize_cjk_title("轻声密语")
        assert result == normalize_cjk_title("輕聲密語")

    def test_lowercase(self) -> None:
        assert normalize_cjk_title("ABC Title") == "abctitle"

    def test_strips_spaces(self) -> None:
        assert normalize_cjk_title("  test   title  ") == "testtitle"

    def test_common_char_pairs(self) -> None:
        assert normalize_cjk_title("轻声密语") == normalize_cjk_title("輕聲密語")
