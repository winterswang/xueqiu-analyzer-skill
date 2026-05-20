"""
xueqiu-analyzer V3 — 评估器单元测试
"""

import json
import pytest
from xueqiu_analyzer.models import (
    CrawlResult, Discussion, News, Notice, Article,
    FinancialData, EvaluationResult,
)
from xueqiu_analyzer.evaluator import Evaluator


class TestParseEvaluationResult:
    """测试评估结果解析 — 核心测试，覆盖各种 LLM 输出格式"""

    def setup_method(self):
        self.evaluator = Evaluator.__new__(Evaluator)
        # 不需要真实 LLM，只测解析逻辑

    def test_parse_json_block(self):
        """LLM 返回 ```json ... ``` 格式"""
        response = '''根据评估，结果如下：

```json
{
  "total_score": 120,
  "scores": {
    "估值分析": {"score": 15, "reason": "有PE讨论", "evidence": "PE=18"},
    "商业模式": {"score": 25, "reason": "深度护城河", "evidence": "微信壁垒"}
  },
  "quality_assessment": {"信息来源可靠性": "一般"},
  "crawl_suggestions": {"优先类型": "研报"}
}
```
'''
        result = self.evaluator._parse_result(response)
        assert result.total_score == 120
        assert result.scores["估值分析"]["score"] == 15
        assert result.scores["商业模式"]["score"] == 25

    def test_parse_plain_json(self):
        """LLM 返回纯 JSON"""
        response = json.dumps({
            "total_score": 90,
            "scores": {
                "估值分析": {"score": 5, "reason": "仅PE数据", "evidence": ""},
            },
            "quality_assessment": {},
            "crawl_suggestions": {},
        })
        result = self.evaluator._parse_result(response)
        assert result.total_score == 90
        assert result.scores["估值分析"]["score"] == 5

    def test_parse_json_with_surrounding_text(self):
        """JSON 前后有文字"""
        response = '''我来评估一下：

{"total_score": 155, "scores": {"估值分析": {"score": 25, "reason": "完整DCF", "evidence": "DCF模型"}}, "quality_assessment": {}, "crawl_suggestions": {}}

以上就是评估结果。'''
        result = self.evaluator._parse_result(response)
        assert result.total_score == 155
        assert result.effective_score == 155
        assert result.is_sufficient is True

    def test_parse_malformed_json(self):
        """LLM 返回格式异常"""
        response = "This is not JSON at all, just text."
        result = self.evaluator._parse_result(response)
        assert result.total_score == 0
        assert result.sufficiency == "未知"

    def test_parse_missing_fields(self):
        """JSON 缺少字段"""
        response = json.dumps({"total_score": 50})
        result = self.evaluator._parse_result(response)
        assert result.total_score == 50
        assert result.scores == {}

    def test_sufficiency_sufficient(self):
        """充分性判定：>=150"""
        result = EvaluationResult(total_score=150, scores={},
                                  financial_bonus=0)
        assert result.is_sufficient is True
        assert result.sufficiency == "不足"  # 默认值，_build_result 会覆盖

    def test_sufficiency_with_bonus(self):
        """财务加分让评分达到充分"""
        result = EvaluationResult(total_score=140, scores={},
                                  financial_bonus=10)
        assert result.effective_score == 150
        assert result.is_sufficient is True

    def test_sufficiency_insufficient(self):
        """充分性判定：<150"""
        result = EvaluationResult(total_score=90, scores={},
                                  financial_bonus=0)
        assert result.effective_score == 90
        assert result.is_sufficient is False


class TestCrawlResultMerge:
    """测试数据合并去重"""

    def test_merge_dedup_by_link(self):
        """按 link 去重"""
        r1 = CrawlResult(
            symbol="00700",
            discussions=[
                Discussion(author="A", content="hello", time="1m",
                           link="https://xueqiu.com/1"),
            ],
        )
        r2 = CrawlResult(
            symbol="00700",
            discussions=[
                Discussion(author="A", content="hello", time="1m",
                           link="https://xueqiu.com/1"),  # 重复
                Discussion(author="B", content="world", time="2m",
                           link="https://xueqiu.com/2"),  # 新增
            ],
        )
        merged = r1.merge(r2)
        assert len(merged.discussions) == 2

    def test_merge_preserves_original(self):
        """合并不修改原始数据"""
        r1 = CrawlResult(symbol="00700", news=[
            News(title="n1", content="c1", time="1m", link="l1"),
        ])
        r2 = CrawlResult(symbol="00700", news=[
            News(title="n2", content="c2", time="2m", link="l2"),
        ])
        merged = r1.merge(r2)
        assert len(merged.news) == 2
        assert len(r1.news) == 1


class TestModels:
    """测试数据模型序列化/反序列化"""

    def test_crawl_result_roundtrip(self):
        """CrawlResult 序列化+反序列化"""
        original = CrawlResult(
            symbol="00700",
            name="腾讯控股",
            discussions=[
                Discussion(author="test", content="hello", time="1m",
                           link="https://xueqiu.com/1"),
            ],
            financial_data=FinancialData(pe_ttm=18.5, pb=3.2),
        )
        d = original.to_dict()
        restored = CrawlResult.from_dict(d)
        assert restored.symbol == "00700"
        assert restored.name == "腾讯控股"
        assert len(restored.discussions) == 1
        assert restored.financial_data.pe_ttm == 18.5

    def test_evaluation_result_roundtrip(self):
        """EvaluationResult 序列化+反序列化"""
        original = EvaluationResult(
            total_score=120,
            scores={"估值分析": {"score": 15, "reason": "test"}},
            sufficiency="基本充分",
            financial_bonus=10,
        )
        d = original.to_dict()
        restored = EvaluationResult.from_dict(d)
        assert restored.total_score == 120
        assert restored.effective_score == 130
        assert restored.scores["估值分析"]["score"] == 15

    def test_financial_data_has_data(self):
        """FinancialData.has_data 判断"""
        fd1 = FinancialData()
        assert fd1.has_data is False

        fd2 = FinancialData(pe_ttm=18.5)
        assert fd2.has_data is True

    def test_crawl_result_total_items(self):
        """total_items 统计"""
        cr = CrawlResult(
            symbol="00700",
            discussions=[Discussion(author="a", content="c", time="1m")],
            news=[News(title="n", content="c", time="1m")],
        )
        assert cr.total_items == 2
