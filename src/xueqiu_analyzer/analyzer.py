"""
xueqiu-analyzer V3 — 深度分析器

生成结构化投资分析报告，支持不同分析模板。
"""

import logging
from pathlib import Path

from .models import CrawlResult, EvaluationResult
from .llm_client import LLMClient
from .config import get_config

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent.parent.parent / 'prompts'


class Analyzer:
    """深度投资分析器"""

    def __init__(self, llm: LLMClient = None, config: dict = None,
                 template: str = 'analysis'):
        self.llm = llm or LLMClient()
        self.config = config or get_config()
        self.template = template

    def analyze(self, data: CrawlResult,
                evaluation: EvaluationResult = None) -> str:
        """
        生成深度分析报告

        Args:
            data: 爬取结果
            evaluation: 评估结果（可选）

        Returns:
            Markdown 格式的分析报告
        """
        prompt = self._build_prompt(data, evaluation)
        return self.llm.analyze(prompt)

    def _build_prompt(self, data: CrawlResult,
                      evaluation: EvaluationResult = None) -> str:
        """构建分析 Prompt"""
        template_path = _PROMPTS_DIR / f'{self.template}.md'
        if template_path.exists():
            template = template_path.read_text(encoding='utf-8')
        else:
            template = self._default_prompt_template()

        # 基础信息
        header = f"""# 分析目标

股票: {data.name} ({data.symbol})
当前价格: {data.price}
涨跌幅: {data.change}

"""

        # 评估摘要
        eval_text = ""
        if evaluation:
            eval_text = f"""# 评估摘要

总分: {evaluation.total_score}/{200 + evaluation.financial_bonus}
充分性: {evaluation.sufficiency}

各主题评分:
"""
            for topic, info in evaluation.scores.items():
                score = info.get('score', 0) if isinstance(info, dict) else 0
                eval_text += f"- {topic}: {score}分\n"

        # 格式化内容（复用 evaluator 的格式化，但更完整）
        content = self._format_content(data)

        # 财务数据
        fin_text = ""
        if data.financial_data and data.financial_data.has_data:
            fd = data.financial_data
            fin_text = f"""# 财务数据

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
                fin_text += "\n## 多年 ROIC\n\n| 年份 | ROIC(%) | NOPAT(亿) | 投入资本(亿) |\n|------|---------|-----------|-------------|\n"
                for row in fd.yearly_roic:
                    fin_text += (f"| {int(row.get('year', 0))} "
                                 f"| {row.get('roic', 0):.2f} "
                                 f"| {row.get('nopat', 0):.2f} "
                                 f"| {row.get('invested_capital', 0):.2f} |\n")

        # 渲染
        prompt = template.replace('{{header}}', header)
        prompt = prompt.replace('{{evaluation}}', eval_text)
        prompt = prompt.replace('{{content}}', content)
        prompt = prompt.replace('{{financial_data}}', fin_text)

        return prompt

    def _format_content(self, data: CrawlResult) -> str:
        """格式化完整内容（分析用，比评估更详细）"""
        parts = []

        if data.articles:
            parts.append(f"## 专栏文章（{len(data.articles)}篇）\n")
            for i, a in enumerate(data.articles, 1):
                parts.append(f"### 文章{i}: {a.title}\n"
                             f"作者: {a.author} | 时间: {a.time}\n\n"
                             f"{a.content}\n")

        if data.discussions:
            parts.append(f"## 热门讨论（{len(data.discussions)}条）\n")
            for i, d in enumerate(data.discussions, 1):
                text = f"### 讨论{i}\n作者: {d.author} | 时间: {d.time}\n\n{d.content}\n"
                if d.comments:
                    text += f"评论: {'; '.join(d.comments[:3])}\n"
                parts.append(text)

        if data.news:
            parts.append(f"## 相关资讯（{len(data.news)}条）\n")
            for i, n in enumerate(data.news, 1):
                parts.append(f"### 资讯{i}: {n.title}\n"
                             f"时间: {n.time} | 来源: {n.source}\n\n"
                             f"{n.content}\n")

        if data.notices:
            parts.append(f"## 公告（{len(data.notices)}条）\n")
            for i, nt in enumerate(data.notices, 1):
                text = f"### 公告{i}: {nt.title}\n时间: {nt.time}\n"
                if nt.pdf_link:
                    text += f"PDF: {nt.pdf_link}\n"
                if nt.content:
                    text += f"\n{nt.content}\n"
                parts.append(text)

        return '\n'.join(parts)

    @staticmethod
    def _default_prompt_template() -> str:
        """默认分析 Prompt"""
        return """你是一位专业的投资分析助手，擅长分析股票投资价值。请用中文回答，输出结构化的投资分析报告。

{{header}}

{{evaluation}}

{{financial_data}}

---

# 以下是需要分析的内容

{{content}}

---

# 输出要求

请生成一份完整的投资分析报告，包含以下部分：

## 一、执行摘要
- 估值判断（高估/合理/低估，附理由）
- 投资建议（买入/持有/卖出，建议仓位）
- 核心投资逻辑（3-4条，每条都要📌引用原文）
- 关键风险

## 二、深度分析
对以下8个主题逐一展开分析，每个分析点都要引用原文数据作为证据：

1. 估值分析
2. 商业模式与护城河
3. 财务质量
4. 竞争格局
5. 管理层与治理
6. 风险因素
7. 用户价值
8. 未来前景

## 三、投资决策
### 入场条件
- 建仓区间、加仓区间、重仓区间及对应仓位

### 跟踪指标
- 财务指标和业务指标

### 退出条件
- 止损条件和止盈条件

请确保每个分析结论都有原文引用（📌格式），不要凭空编造数据。"""
