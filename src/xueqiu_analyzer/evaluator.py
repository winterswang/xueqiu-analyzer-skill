"""
xueqiu-analyzer V3 — 评估器

评估信息充分性，输出结构化评估结果。
"""

import json
import re
import logging
from typing import Optional
from pathlib import Path

from .models import (
    CrawlResult, EvaluationResult, SCORING_CRITERIA, format_content, FORMAT_LIMITS_EVAL
)
from .llm_client import LLMClient
from .config import get_config

logger = logging.getLogger(__name__)

# Prompt 模板目录
_PROMPTS_DIR = Path(__file__).parent.parent.parent / 'prompts'


class Evaluator:
    """信息充分性评估器"""

    def __init__(self, llm: LLMClient = None, config: dict = None):
        self.llm = llm or LLMClient()
        self.config = config or get_config()

    def evaluate(self, data: CrawlResult) -> EvaluationResult:
        """
        评估数据充分性

        Args:
            data: 爬取结果

        Returns:
            EvaluationResult
        """
        prompt = self._build_prompt(data)
        response = self.llm.evaluate(prompt)
        result = self._parse_result(response)

        # 补充 token 统计
        result.token_stats = self._calc_token_stats(data)

        return result

    def _build_prompt(self, data: CrawlResult) -> str:
        """构建评估 Prompt"""
        # 加载 Prompt 模板
        template_path = _PROMPTS_DIR / 'evaluation.md'
        if template_path.exists():
            template = template_path.read_text(encoding='utf-8')
        else:
            template = self._default_prompt_template()

        # 格式化内容
        content = self._format_content(data)

        # 渲染模板
        prompt = template.replace('{{content}}', content)
        prompt = prompt.replace('{{scoring_criteria}}',
                                json.dumps(SCORING_CRITERIA,
                                           ensure_ascii=False, indent=2))

        # 财务数据
        if data.financial_data and data.financial_data.has_data:
            fd = data.financial_data
            fin_text = f"""
# 财务数据

| 指标 | 数值 |
|------|------|
| PE (TTM) | {fd.pe_ttm:.1f} |
| PB | {fd.pb:.1f} |
| ROE | {fd.roe:.1f}% |
| 毛利率 | {fd.gross_margin:.1f}% |
| 净利率 | {fd.net_margin:.1f}% |
| 营收增速 | {fd.revenue_growth:.1f}% |
| 利润增速 | {fd.profit_growth:.1f}% |
| 52周高低 | {fd.low52w:.1f} - {fd.high52w:.1f} |
"""
            if fd.has_roic:
                fin_text += "\n## 多年 ROIC\n\n| 年份 | ROIC(%) |\n|------|--------|\n"
                for row in fd.yearly_roic:
                    fin_text += f"| {int(row.get('year', 0))} | {row.get('roic', 0):.2f} |\n"
                fin_text += "\n**财务数据加分项：+10分（多年ROIC数据可用）**\n"

            prompt = prompt.replace('{{financial_data}}', fin_text)
        else:
            prompt = prompt.replace('{{financial_data}}', '（未获取财务数据）')

        return prompt

    def _format_content(self, data: CrawlResult) -> str:
        """格式化爬取内容（评估用，截断模式）"""
        return format_content(data, FORMAT_LIMITS_EVAL)

    def _parse_result(self, response: str) -> EvaluationResult:
        """
        解析 LLM 返回的评估结果

        支持格式：
        1. ```json ... ```
        2. 纯 JSON
        3. 夹杂文本中的 JSON
        """
        # 尝试提取 JSON
        json_str = self._extract_json(response)

        if json_str:
            try:
                data = json.loads(json_str)
                return self._build_result(data)
            except json.JSONDecodeError as e:
                logger.warning(f"评估结果 JSON 解析失败: {e}")

        # 解析失败，返回默认结果
        logger.warning("评估结果解析失败，使用默认值")
        return EvaluationResult(
            total_score=0,
            sufficiency="未知",
            need_more_crawl=True,
        )

    def _extract_json(self, text: str) -> Optional[str]:
        """从文本中提取 JSON"""
        # 方法1: ```json ... ```
        match = re.search(r'```json\s*(.*?)\s*```', text, re.DOTALL)
        if match:
            return match.group(1)

        # 方法2: ``` ... ```
        match = re.search(r'```\s*(.*?)\s*```', text, re.DOTALL)
        if match:
            candidate = match.group(1).strip()
            if candidate.startswith('{'):
                return candidate

        # 方法3: 找最外层 { }
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end > start:
            return text[start:end + 1]

        return None

    def _build_result(self, data: dict) -> EvaluationResult:
        """从解析的 dict 构建评估结果"""
        total_score = data.get('total_score', 0)
        scores = data.get('scores', {})
        financial_bonus = data.get('financial_bonus', 0)

        # 如果有多年 ROIC 但没加分，自动加
        financial_bonus = financial_bonus or 0

        effective = total_score + financial_bonus
        if effective >= 150:
            sufficiency = "充分"
            need_more = False
        elif effective >= 100:
            sufficiency = "基本充分"
            need_more = True
        else:
            sufficiency = "不足"
            need_more = True

        return EvaluationResult(
            total_score=total_score,
            scores=scores,
            sufficiency=sufficiency,
            need_more_crawl=need_more,
            crawl_suggestions=data.get('crawl_suggestions', {}),
            quality_assessment=data.get('quality_assessment', {}),
            financial_bonus=financial_bonus,
        )

    def _calc_token_stats(self, data: CrawlResult) -> dict:
        """计算 token 统计"""
        articles_chars = sum(len(a.content) for a in data.articles)
        discussions_chars = sum(len(d.content) for d in data.discussions)
        news_chars = sum(len(n.title) + len(n.content) for n in data.news)
        notices_chars = sum(len(nt.title) + len(nt.content)
                           for nt in data.notices)

        return {
            'articles': {'count': len(data.articles),
                         'tokens': articles_chars * 2},
            'discussions': {'count': len(data.discussions),
                            'tokens': discussions_chars * 2},
            'news': {'count': len(data.news),
                     'tokens': news_chars * 2},
            'notices': {'count': len(data.notices),
                        'tokens': notices_chars * 2},
            'total_tokens': (articles_chars + discussions_chars +
                             news_chars + notices_chars) * 2,
        }

    @staticmethod
    def _default_prompt_template() -> str:
        """默认评估 Prompt 模板（当 prompts/evaluation.md 不存在时使用）"""
        return """你是一位资深价值投资分析师，现在需要评估当前收集的信息是否足够支撑一份高质量的投资分析报告。

# 评分标准

{{scoring_criteria}}

# 爬取内容

{{content}}

{{financial_data}}

# 输出格式

请以JSON格式输出评估结果，包含以下字段：

```json
{
  "total_score": 数字(0-200),
  "scores": {
    "估值分析": {"score": 数字, "reason": "理由", "evidence": "原文证据"},
    "商业模式": {"score": 数字, "reason": "理由", "evidence": "原文证据"},
    "财务质量": {"score": 数字, "reason": "理由", "evidence": "原文证据"},
    "竞争格局": {"score": 数字, "reason": "理由", "evidence": "原文证据"},
    "管理层": {"score": 数字, "reason": "理由", "evidence": "原文证据"},
    "风险因素": {"score": 数字, "reason": "理由", "evidence": "原文证据"},
    "用户价值": {"score": 数字, "reason": "理由", "evidence": "原文证据"},
    "未来前景": {"score": 数字, "reason": "理由", "evidence": "原文证据"}
  },
  "quality_assessment": {
    "信息来源可靠性": "评价",
    "观点多样性": "评价",
    "深度文章数": 数字
  },
  "crawl_suggestions": {
    "优先类型": "建议",
    "关注主题": "建议",
    "原因": "说明"
  }
}
```

请严格按照JSON格式输出，不要添加额外文字。"""
