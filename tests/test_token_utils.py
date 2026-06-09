"""Tests for token_utils — estimate_tokens, build_batches."""
import pytest
from xueqiu_analyzer.token_utils import estimate_tokens, build_batches


class TestEstimateTokens:
    def test_chinese_reasonable(self):
        """Chinese text should estimate 0.5-2 tokens per char."""
        n = estimate_tokens("你好世界")
        # len*2=8 (upper bound), tiktoken=~4-5 (typical)
        assert 4 <= n <= 8

    def test_english_reasonable(self):
        """English text should be much less than len*2."""
        n = estimate_tokens("hello")
        # len*2=10 , tiktoken=1
        assert 1 <= n <= 10

    def test_empty(self):
        assert estimate_tokens("") == 0

    def test_mixed_reasonable(self):
        text = "AK112 HR=0.66 降低死亡风险34%"
        n = estimate_tokens(text)
        # len*2=46, tiktoken~22
        assert 15 <= n <= len(text) * 2

    def test_long_chinese(self):
        """Long Chinese text: verify tokenize doesn't explode."""
        text = "这是一个较长的中文测试句子，用于验证token估算在长文本下的表现。" * 20
        n = estimate_tokens(text)
        assert 100 < n < len(text) * 2

    def test_pure_numbers(self):
        n = estimate_tokens("1234567890")
        assert 1 <= n <= 20


class TestBuildBatches:
    def test_single_batch_fits(self):
        items = [{"content": "短" * 100, "author": "A"}]
        batches = build_batches(items, max_content_tokens=63000)
        assert len(batches) == 1
        assert len(batches[0]) == 1

    def test_split_on_overflow(self):
        """Large items should split into multiple batches."""
        long_text = "长" * 6000   # ~6K tokens with tiktoken
        items = [{"content": long_text, "author": "X"} for _ in range(7)]
        batches = build_batches(items, max_content_tokens=20000)
        assert len(batches) >= 2, f"Expected >=2 batches, got {len(batches)}"

    def test_empty_input(self):
        assert build_batches([], max_content_tokens=63000) == []

    def test_large_item_gets_own_batch(self):
        """Overflowing item should go to next batch."""
        huge = "大" * 50000  # exceeds limit
        items = [{"content": huge, "author": "X"},
                 {"content": "小", "author": "Y"}]
        batches = build_batches(items, max_content_tokens=20000)
        assert len(batches) >= 2, f"Expected >=2 batches, got {len(batches)}"
        assert sum(len(b) for b in batches) == 2

    def test_custom_limit(self):
        items = [{"content": "x" * 100, "author": "A"} for _ in range(5)]
        batches = build_batches(items, max_content_tokens=100, max_items=2)
        assert len(batches) >= 3   # 5 items / 2 per batch = 3 batches

    def test_mixed_content_lengths(self):
        """Short + long items should batch correctly."""
        items = [
            {"content": "短", "author": "A"},
            {"content": "长" * 30000, "author": "B"},
            {"content": "短", "author": "C"},
            {"content": "短", "author": "D"},
        ]
        batches = build_batches(items, max_content_tokens=20000)
        # item 2 is huge → should cause a split
        assert len(batches) >= 2, f"Expected >=2 batches, got {len(batches)}"
        # Verify all items are preserved
        total = sum(len(b) for b in batches)
        assert total == 4
