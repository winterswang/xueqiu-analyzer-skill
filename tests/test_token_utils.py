import pytest
from xueqiu_analyzer.token_utils import estimate_tokens, build_batches


class TestEstimateTokens:
    def test_chinese(self):
        assert estimate_tokens("你好世界") == 8

    def test_english(self):
        assert estimate_tokens("hello") == 10

    def test_empty(self):
        assert estimate_tokens("") == 0

    def test_mixed(self):
        text = "AK112 HR=0.66 降低死亡风险34%"
        assert estimate_tokens(text) == len(text) * 2


class TestBuildBatches:
    def test_single_batch_fits(self):
        items = [{"content": "短帖" * 10, "author": "A"}]  # ~300 tokens
        batches = build_batches(items, max_content_tokens=63000)
        assert len(batches) == 1
        assert len(batches[0]) == 1

    def test_split_on_overflow(self):
        # 每条 ~10K tokens, 7条 → batch1:6条 ~60K, batch2:1条
        long = "长" * 4500  # ~9K chars → ~18K tokens
        items = [{"content": long, "author": "X"} for _ in range(7)]
        batches = build_batches(items, max_content_tokens=63000)
        assert len(batches) >= 2

    def test_empty_input(self):
        assert build_batches([], max_content_tokens=63000) == []

    def test_large_item_gets_own_batch(self):
        huge = "大" * 40000  # ~80K tokens, exceeds limit
        items = [{"content": huge, "author": "X"},
                 {"content": "小", "author": "Y"}]
        batches = build_batches(items, max_content_tokens=63000)
        assert len(batches) == 2
        assert len(batches[0]) == 1
        assert len(batches[1]) == 1
