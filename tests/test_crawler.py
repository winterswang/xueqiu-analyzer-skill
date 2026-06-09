"""Tests for crawler.py text cleaning utilities."""

import pytest
from xueqiu_analyzer.crawler import clean_pua


class TestCleanPua:
    """Verify PUA and invisible-formatting character removal."""

    def test_strips_icon_font_chars(self):
        """\ue62d \ue64b \ue633 \ue62f — xueqiu's common icon font glyphs."""
        raw = "海外市场\uE62D\uE64B讨论\uE633"
        assert clean_pua(raw) == "海外市场讨论"

    def test_invisible_formatting(self):
        """U+200B (zero-width space) and friends."""
        raw = "hello\u200Bworld\u200Ctest\u200D!"
        assert clean_pua(raw) == "helloworldtest!"

    def test_preserves_normal_text(self):
        text = "贵州茅台2024年报：营收增长15%"
        assert clean_pua(text) == text

    def test_empty_string(self):
        assert clean_pua("") == ""

    def test_only_pua_chars(self):
        assert clean_pua("\uE62D\uE64B") == ""

    def test_mixed_pua_and_formatting(self):
        """Both PUA and invisible formatting in one string."""
        raw = "\uE62D点赞\u200B\uE64B转发\u200C\uE633"
        assert clean_pua(raw) == "点赞转发"

    def test_idempotent(self):
        """Re-cleaning should be a no-op."""
        text = "clean text already"
        assert clean_pua(clean_pua(text)) == text
