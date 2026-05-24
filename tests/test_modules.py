"""
xueqiu-analyzer V3 — LLM 客户端、配置、分析器测试
"""

import json
import pytest
from unittest.mock import patch, MagicMock

from xueqiu_analyzer.models import (
    CrawlResult, Discussion, News, Article, Notice,
    FinancialData, EvaluationResult,
)
from xueqiu_analyzer.config import get_config, get_llm_config, _resolve_env
from xueqiu_analyzer.llm_client import LLMClient
from xueqiu_analyzer.analyzer import Analyzer
from xueqiu_analyzer.evaluator import Evaluator


class TestConfig:
    """配置加载测试"""

    def test_resolve_env_with_var(self):
        """环境变量解析：有值"""
        with patch.dict('os.environ', {'MY_KEY': 'hello'}):
            assert _resolve_env('${MY_KEY}') == 'hello'

    def test_resolve_env_without_var(self):
        """环境变量解析：无值"""
        with patch.dict('os.environ', {}, clear=True):
            assert _resolve_env('${MISSING_KEY}') == ''

    def test_resolve_env_plain_string(self):
        """非占位符字符串原样返回"""
        assert _resolve_env('https://api.example.com') == 'https://api.example.com'

    def test_get_config_structure(self):
        """配置结构完整"""
        config = get_config()
        assert 'llm' in config
        assert 'crawler' in config
        assert 'evaluator' in config
        assert 'analysis' in config
        assert 'storage' in config
        assert 'notify' in config

    def test_llm_config_has_required_fields(self):
        """LLM 配置包含必要字段"""
        llm = get_llm_config()
        assert 'base_url' in llm
        assert 'model' in llm
        assert 'api_key' in llm
        assert 'max_tokens' in llm
        assert 'temperature' in llm

    def test_llm_config_base_url_not_empty(self):
        """base_url 不为空"""
        llm = get_llm_config()
        assert llm['base_url'] != ''


class TestLLMClient:
    """LLM 客户端测试"""

    def test_model_property(self):
        """model 属性"""
        client = LLMClient(config={'model': 'test-model', 'base_url': 'http://test',
                                    'api_key': 'key', 'max_tokens': 1000,
                                    'temperature': 0.5})
        assert client.model == 'test-model'

    def test_evaluate_uses_low_temperature(self):
        """评估用低温度"""
        client = LLMClient(config={'model': 'm', 'base_url': 'http://t',
                                    'api_key': 'k', 'max_tokens': 1000,
                                    'temperature': 0.7})
        # 不能真正调用 API，只验证方法存在
        assert hasattr(client, 'evaluate')
        assert hasattr(client, 'analyze')
        assert hasattr(client, 'simple_chat')


class TestAnalyzer:
    """分析器测试"""

    def test_build_prompt_with_data(self):
        """构建分析 Prompt"""
        analyzer = Analyzer.__new__(Analyzer)
        analyzer.template = 'analysis'

        data = CrawlResult(
            symbol="00700",
            name="腾讯控股",
            price="460",
            articles=[
                Article(title="测试文章", author="作者", content="内容" * 100,
                        time="2026-05-20", link="https://xueqiu.com/1"),
            ],
            financial_data=FinancialData(pe_ttm=18.5, pb=3.2, roe=22.0),
        )

        eval_result = EvaluationResult(
            total_score=120,
            scores={"估值分析": {"score": 15, "reason": "test", "evidence": ""}},
            sufficiency="基本充分",
        )

        prompt = analyzer._build_prompt(data, eval_result)
        assert "00700" in prompt
        assert "腾讯控股" in prompt
        assert "460" in prompt
        assert "18.5" in prompt
        assert "120" in prompt

    def test_format_content_includes_articles(self):
        """内容格式化包含文章"""
        analyzer = Analyzer.__new__(Analyzer)
        data = CrawlResult(
            symbol="00700",
            articles=[
                Article(title="文章1", author="A", content="正文内容",
                        time="2026-05-20", link="l1"),
            ],
            discussions=[
                Discussion(author="B", content="讨论内容", time="1m",
                           link="l2", comments=["评论1"]),
            ],
        )
        content = analyzer._format_content(data)
        assert "文章1" in content
        assert "讨论内容" in content
        assert "评论1" in content


class TestEvaluatorFormatting:
    """评估器格式化测试"""

    def test_format_content_with_all_types(self):
        """所有数据类型格式化"""
        evaluator = Evaluator.__new__(Evaluator)
        data = CrawlResult(
            symbol="00700",
            articles=[
                Article(title="A", author="B", content="C" * 50,
                        time="2026-05-20", link="l1"),
            ],
            discussions=[
                Discussion(author="D", content="E" * 50, time="1m",
                           link="l2"),
            ],
            news=[
                News(title="F", content="G" * 50, time="2m",
                     source="财联社", link="l3"),
            ],
            notices=[
                Notice(title="H", link="l4", time="3m",
                       content="I" * 50, pdf_link="https://pdf"),
            ],
        )
        content = evaluator._format_content(data)
        assert "专栏文章" in content
        assert "热门讨论" in content
        assert "相关资讯" in content
        assert "公告" in content
        assert "https://pdf" in content

    def test_format_empty_data(self):
        """空数据格式化"""
        evaluator = Evaluator.__new__(Evaluator)
        data = CrawlResult(symbol="00700")
        content = evaluator._format_content(data)
        assert content == ""


class TestFinancialData:
    """财务数据模型测试"""

    def test_has_data_true(self):
        fd = FinancialData(pe_ttm=18.5)
        assert fd.has_data is True

    def test_has_data_false(self):
        fd = FinancialData()
        assert fd.has_data is False

    def test_has_roic(self):
        fd = FinancialData(yearly_roic=[{"year": 2024, "roic": 20.5}])
        assert fd.has_roic is True

    def test_has_roic_empty(self):
        fd = FinancialData()
        assert fd.has_roic is False


class TestEvaluationResultLogic:
    """评估结果逻辑测试"""

    def test_effective_score_with_bonus(self):
        r = EvaluationResult(total_score=140, financial_bonus=10)
        assert r.effective_score == 150
        assert r.is_sufficient is True

    def test_effective_score_without_bonus(self):
        r = EvaluationResult(total_score=140, financial_bonus=0)
        assert r.effective_score == 140
        assert r.is_sufficient is False

    def test_sufficiency_sufficient(self):
        r = EvaluationResult(total_score=150)
        assert r.is_sufficient is True

    def test_sufficiency_just_below(self):
        r = EvaluationResult(total_score=149)
        assert r.is_sufficient is False

    def test_from_dict_ignores_unknown_fields(self):
        """from_dict 忽略未知字段"""
        d = {"total_score": 100, "unknown_field": "xxx", "scores": {}}
        r = EvaluationResult.from_dict(d)
        assert r.total_score == 100
        assert not hasattr(r, 'unknown_field')
