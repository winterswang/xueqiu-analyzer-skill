#!/usr/bin/env python3
"""
智能迭代爬取系统 V2.1

更新内容：
1. 最大爬取轮次：10轮
2. API超时：30分钟
3. 终止条件：评分>=150或最大轮次
4. Token统计：分项统计文章/讨论/资讯/公告

核心设计：
1. 每轮爬取后，用全部内容调用 Prompt 1 评估
2. 根据评分决定是否继续爬取（最多10轮）
3. 评分>=150可提前终止
4. 信息充分后，用全部内容调用 Prompt 2 深度分析
"""

import os
import sys
import json
import time
import re
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict

sys.path.insert(0, str(Path(__file__).parent))

from stock_crawler_v2 import XueqiuStockCrawlerV2
from financial_fetcher import FinancialDataFetcher


@dataclass
class EvaluationResult:
    """评估结果"""
    total_score: int
    scores: Dict[str, Dict]
    sufficiency: str
    need_more_crawl: bool
    crawl_suggestions: Dict
    quality_assessment: Dict


class SmartCrawlerV2:
    """智能迭代爬取系统 V2"""
    
    # 评分标准（基于价值投资者需求）
    SCORING_CRITERIA = {
        "估值分析": {
            "25": "有完整估值模型/DCF分析",
            "15": "有估值讨论（PE/PB对比等）",
            "5": "仅有PE/PB数据",
            "0": "无估值相关内容"
        },
        "商业模式": {
            "25": "深度护城河分析，讨论可持续性",
            "15": "讨论竞争优势和行业地位",
            "5": "仅提及行业地位",
            "0": "无商业模式相关内容"
        },
        "财务质量": {
            "25": "完整财务分析（现金流、ROE趋势等）",
            "15": "部分财务指标讨论",
            "5": "仅有财务数据",
            "0": "无财务相关内容"
        },
        "竞争格局": {
            "25": "深度竞争分析，讨论行业格局演变",
            "15": "提及主要竞争对手和威胁",
            "5": "仅提及竞争",
            "0": "无竞争相关内容"
        },
        "管理层": {
            "25": "深度管理层分析（履历、战略、配置）",
            "15": "提及管理层变动或治理",
            "5": "仅提高管姓名",
            "0": "无管理层相关内容"
        },
        "风险因素": {
            "25": "系统性风险分析，多维度评估",
            "15": "提及主要风险点",
            "5": "仅有负面情绪表达",
            "0": "无风险相关内容"
        },
        "用户价值": {
            "25": "真实用户深度反馈（体验、忠诚度）",
            "15": "有用户评论或反馈",
            "5": "仅提用户数量",
            "0": "无用户相关内容"
        },
        "未来前景": {
            "25": "清晰增长逻辑和催化剂分析",
            "15": "提及增长方向和机会",
            "5": "仅提增长数据",
            "0": "无前景相关内容"
        }
    }
    
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.all_articles: List[dict] = []
        self.all_discussions: List[dict] = []
        self.all_news: List[dict] = []
        self.all_notices: List[dict] = []  # 新增公告
        self.seen_links: set = set()
        self.cookies: List = None
        self.financial_data: dict = {}
        
    def crawl_round(self, max_pages: int = 3, max_articles: int = 10) -> dict:
        """执行一轮爬取"""
        print(f"\n  爬取参数: max_pages={max_pages}, max_articles={max_articles}")
        
        crawler = XueqiuStockCrawlerV2(headless=True)
        
        result = crawler.crawl(
            symbol=self.symbol,
            max_discussions=30,
            max_news=30,
            max_articles=max_articles,
            max_scrolls=max_pages
        )
        
        data = crawler.to_dict(result)
        
        # 合并数据（去重 - 按类型分别去重）
        new_count = {'articles': 0, 'discussions': 0, 'news': 0}
        
        # 文章去重
        for a in data.get('articles', []):
            link = a.get('link', '')
            article_key = f"article:{link}"
            if link and article_key not in self.seen_links:
                self.seen_links.add(article_key)
                self.all_articles.append(a)
                new_count['articles'] += 1
        
        # 讨论去重
        for d in data.get('discussions', []):
            link = d.get('link', '')
            discussion_key = f"discussion:{link}"
            if link and discussion_key not in self.seen_links:
                self.seen_links.add(discussion_key)
                self.all_discussions.append(d)
                new_count['discussions'] += 1
        
        # 资讯去重
        for n in data.get('news', []):
            link = n.get('link', '')
            news_key = f"news:{link}"
            if link and news_key not in self.seen_links:
                self.seen_links.add(news_key)
                self.all_news.append(n)
                new_count['news'] += 1
        
        # 公告去重
        new_count['notices'] = 0
        for n in data.get('notices', []):
            link = n.get('link', '')
            notice_key = f"notice:{link}"
            if link and notice_key not in self.seen_links:
                self.seen_links.add(notice_key)
                self.all_notices.append(n)
                new_count['notices'] += 1
        
        print(f"  新增: {new_count['articles']} 文章, {new_count['discussions']} 讨论, {new_count['news']} 资讯, {new_count['notices']} 公告")
        print(f"  累计: {len(self.all_articles)} 文章, {len(self.all_discussions)} 讨论, {len(self.all_news)} 资讯, {len(self.all_notices)} 公告")
        
        return new_count
    
    def fetch_financial_data(self):
        """获取财务数据"""
        cookies_path = Path(__file__).parent.parent / 'config' / 'xueqiu_cookies.json'
        if cookies_path.exists():
            with open(cookies_path, 'r') as f:
                self.cookies = json.load(f)
        
        fetcher = FinancialDataFetcher()
        result = fetcher.fetch(self.symbol, self.cookies)
        if result:
            self.financial_data = fetcher.to_dict(result)
            print(f"\n  财务数据: PE={result.pe_ttm:.1f}, PB={result.pb:.1f}, ROE={result.roe:.1f}%")
    
    def build_evaluation_prompt(self) -> str:
        """构建 Prompt 1：信息充分性评估"""
        
        # 构建完整内容
        content_parts = []
        
        # 专栏文章
        content_parts.append("# 专栏文章（完整内容）\n")
        for i, a in enumerate(self.all_articles, 1):
            title = a.get('title', '无标题')
            author = a.get('author', '未知')
            content = a.get('content', '')
            link = a.get('link', '')
            
            content_parts.append(f"\n## 文章 {i}: {title}")
            content_parts.append(f"作者: {author}")
            content_parts.append(f"链接: {link}\n")
            content_parts.append(content)
            content_parts.append("\n---\n")
        
        # 热门讨论
        content_parts.append("\n# 热门讨论（完整内容）\n")
        for i, d in enumerate(self.all_discussions, 1):
            content = d.get('content', '')
            author = d.get('author', '未知')
            content_parts.append(f"\n[{i}] {author}: {content}")
        
        # 财务数据
        fin_text = ""
        if self.financial_data:
            fin_text = f"""
# 财务数据

| 指标 | 数值 |
|------|------|
| PE | {self.financial_data.get('pe_ttm', 0):.1f} |
| PB | {self.financial_data.get('pb', 0):.1f} |
| ROE | {self.financial_data.get('roe', 0):.1f}% |
| 毛利率 | {self.financial_data.get('gross_margin', 0):.1f}% |
| 净利率 | {self.financial_data.get('net_margin', 0):.1f}% |
| 营收增速 | {self.financial_data.get('revenue_growth', 0):.1f}% |
| 利润增速 | {self.financial_data.get('profit_growth', 0):.1f}% |
| 52周高低 | {self.financial_data.get('low52w', 0):.1f} - {self.financial_data.get('high52w', 0):.1f} |
"""
        
        # 评分标准表格
        criteria_text = "\n| 主题 | 25分标准 | 15分标准 | 5分标准 | 0分 |\n|------|----------|----------|---------|-----|\n"
        for topic, criteria in self.SCORING_CRITERIA.items():
            criteria_text += f"| {topic} | {criteria['25']} | {criteria['15']} | {criteria['5']} | {criteria['0']} |\n"
        
        prompt = f"""你是一位资深价值投资分析师，现在需要评估当前收集的信息是否足够支撑一份高质量的投资分析报告。

# 评估目标

作为价值投资者，我需要回答以下8个核心问题：

1. 这家公司值多少钱？（估值分析）
2. 这门生意好不好？（商业模式）
3. 赚钱能力强吗？（财务质量）
4. 竞争对手怎么样？（竞争格局）
5. 管理层靠得住吗？（管理层）
6. 可能出什么问题？（风险因素）
7. 用户怎么说？（用户价值）
8. 还能增长吗？（未来前景）

# 当前收集的完整信息

{"".join(content_parts)}

{fin_text}

# 评分标准

每个主题满分25分，总分200分：

{criteria_text}

# 评估要求

请评估以上信息，输出以下内容：

1. **各主题评分**：对8个主题逐一评分，说明评分理由（必须引用原文证据）
2. **内容覆盖分析**：哪些方面充分？哪些缺失？
3. **质量评估**：信息来源是否可靠？观点是否多元？
4. **爬取建议**：
   - 总分 >= 150：信息充分，可以进入分析
   - 总分 100-150：信息基本充分，建议补充
   - 总分 < 100：信息不足，必须继续爬取

# 输出格式（严格JSON）

```json
{{
  "scores": {{
    "估值分析": {{"score": 15, "reason": "有PE/PB数据和估值讨论，但缺少DCF模型", "evidence": "引用原文..."}},
    "商业模式": {{"score": 25, "reason": "有完整的护城河分析文章", "evidence": "引用原文..."}},
    ...
  }},
  "total_score": 145,
  "sufficiency": "基本充分",
  "coverage_analysis": {{
    "strengths": ["商业模式", "竞争格局", "风险因素"],
    "gaps": ["管理层", "用户价值"]
  }},
  "quality_assessment": {{
    "source_reliability": "信息来源多元",
    "viewpoint_diversity": "有多空双方观点",
    "deep_articles_count": 3
  }},
  "need_more_crawl": true,
  "crawl_suggestions": {{
    "priority": ["讨论", "专栏"],
    "focus_topics": ["管理层", "用户价值"],
    "reason": "缺少管理层分析和真实用户反馈"
  }}
}}
```

请仔细阅读所有内容后，给出准确的评分和建议。
"""
        return prompt
    
    def build_analysis_prompt(self) -> str:
        """构建 Prompt 2：深度分析"""
        
        # 完整内容
        content_parts = []
        
        # 1. 专栏文章
        content_parts.append("# 专栏文章（完整内容）\n")
        for i, a in enumerate(self.all_articles, 1):
            title = a.get('title', '无标题')
            author = a.get('author', '未知')
            content = a.get('content', '')
            link = a.get('link', '')
            
            content_parts.append(f"\n## 文章 {i}: {title}")
            content_parts.append(f"作者: {author}")
            content_parts.append(f"链接: {link}\n")
            content_parts.append(content)
            content_parts.append("\n---\n")
        
        # 2. 热门讨论
        content_parts.append("\n# 热门讨论（完整内容）\n")
        for i, d in enumerate(self.all_discussions, 1):
            content = d.get('content', '')
            author = d.get('author', '未知')
            content_parts.append(f"\n[{i}] {author}: {content}")
        
        # 3. 相关资讯
        if self.all_news:
            content_parts.append("\n# 相关资讯（完整内容）\n")
            for i, n in enumerate(self.all_news, 1):
                title = n.get('title', '无标题')
                time_str = n.get('time', '')
                link = n.get('link', '')
                content = n.get('content', '')
                
                content_parts.append(f"\n## 资讯 {i}: {title}")
                content_parts.append(f"时间: {time_str}")
                content_parts.append(f"链接: {link}\n")
                if content:
                    content_parts.append(content)
                else:
                    content_parts.append("（无正文内容）")
                content_parts.append("\n---\n")
        
        # 4. 公告
        if hasattr(self, 'all_notices') and self.all_notices:
            content_parts.append("\n# 公告\n")
            for i, n in enumerate(self.all_notices, 1):
                title = n.get('title', '公告')
                link = n.get('link', '')
                content_parts.append(f"\n[{i}] {title}")
                content_parts.append(f"链接: {link}")
        
        # 5. 财务数据
        fin_text = ""
        if self.financial_data:
            fin_text = f"""
# 财务数据

| 指标 | 数值 |
|------|------|
| PE | {self.financial_data.get('pe_ttm', 0):.1f} |
| PB | {self.financial_data.get('pb', 0):.1f} |
| ROE | {self.financial_data.get('roe', 0):.1f}% |
| 毛利率 | {self.financial_data.get('gross_margin', 0):.1f}% |
| 净利率 | {self.financial_data.get('net_margin', 0):.1f}% |
| 营收增速 | {self.financial_data.get('revenue_growth', 0):.1f}% |
| 利润增速 | {self.financial_data.get('profit_growth', 0):.1f}% |
| 52周高低 | {self.financial_data.get('low52w', 0):.1f} - {self.financial_data.get('high52w', 0):.1f} |
"""
        
        prompt = f"""你是一位资深价值投资分析师，擅长深度分析上市公司投资价值。

请基于以下详实的信息，输出一份高质量的投资分析报告。

{"".join(content_parts)}

{fin_text}

# 分析框架

请围绕以下8个核心问题展开分析：

1. **估值分析**：这家公司值多少钱？
2. **商业模式**：这门生意好不好？
3. **财务质量**：赚钱能力强吗？
4. **竞争格局**：竞争对手怎么样？
5. **管理层**：管理层靠得住吗？
6. **风险因素**：可能出什么问题？
7. **用户价值**：用户怎么说？
8. **未来前景**：还能增长吗？

# 输出结构

## 一、执行摘要

### 估值判断
- 当前估值：低估/合理/高估
- 判断依据：（引用原文）

### 投资建议
- 操作方向：买入/观望/卖出
- 建议仓位：具体百分比

### 核心投资逻辑（3-5条）
每条逻辑必须引用原文证据

### 关键风险
- 最大风险点

## 二、深度分析

### 2.1 估值分析
（引用原文）

### 2.2 商业模式与护城河
（引用原文）

### 2.3 财务质量
（引用原文）

### 2.4 竞争格局
（引用原文）

### 2.5 管理层与治理
（引用原文）

### 2.6 风险因素
（引用原文）

### 2.7 用户价值
（引用原文）

### 2.8 未来前景
（引用原文）

## 三、投资决策

### 入场条件
- 价格条件
- 时间条件

### 跟踪指标
- 财务指标
- 业务指标

### 退出条件
- 止损条件
- 止盈条件

# 重要规则

1. **必须引用原文**：每个关键观点都要标注来源，格式：> 📌 引用自《文章标题》："原文内容"
2. **定量分析**：尽量使用具体数字
3. **多空平衡**：既要分析利好，也要分析风险
4. **可操作性**：投资建议要具体、可执行
"""
        return prompt
    
    def call_llm(self, prompt: str, max_tokens: int = 4000) -> str:
        """调用 LLM"""
        import urllib.request
        
        config_path = os.path.expanduser('~/.openclaw/openclaw.json')
        with open(config_path, 'r') as f:
            config = json.load(f)
        
        provider = config.get('models', {}).get('providers', {}).get('qwencode', {})
        api_key = provider.get('apiKey', '')
        base_url = provider.get('baseUrl', '')
        
        data = {
            "model": "glm-5",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": 0.7
        }
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        req = urllib.request.Request(
            f"{base_url}/chat/completions",
            data=json.dumps(data).encode('utf-8'),
            headers=headers,
            method='POST'
        )
        
        with urllib.request.urlopen(req, timeout=1800) as resp:
            result = json.loads(resp.read().decode('utf-8'))
            return result['choices'][0]['message']['content']
    
    def parse_evaluation_result(self, response: str) -> Optional[EvaluationResult]:
        """解析评估结果"""
        try:
            # 提取 JSON
            json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group(1))
                return EvaluationResult(
                    total_score=data.get('total_score', 0),
                    scores=data.get('scores', {}),
                    sufficiency=data.get('sufficiency', ''),
                    need_more_crawl=data.get('need_more_crawl', False),
                    crawl_suggestions=data.get('crawl_suggestions', {}),
                    quality_assessment=data.get('quality_assessment', {})
                )
        except Exception as e:
            print(f"  解析评估结果失败: {e}")
        return None
    
    def run(self, max_rounds: int = 10) -> dict:
        """执行智能迭代爬取
        
        Args:
            max_rounds: 最大爬取轮次（默认10）
        """
        print(f"\n{'='*60}")
        print(f"智能迭代爬取系统 V2: {self.symbol}")
        print(f"{'='*60}")
        print(f"配置: 最大轮次={max_rounds}, 超时=30分钟, 终止分数>=150")
        
        # 获取财务数据（一次性）
        print("\n[准备] 获取财务数据...")
        self.fetch_financial_data()
        
        evaluation_result = None
        total_new_content = {'articles': 0, 'discussions': 0, 'news': 0, 'notices': 0}
        
        for round_num in range(1, max_rounds + 1):
            print(f"\n{'='*40}")
            print(f"第 {round_num}/{max_rounds} 轮")
            print(f"{'='*40}")
            
            # 爬取参数：逐步增加
            pages = min(5 + round_num, 10)  # 最大10页
            articles = min(10 + round_num * 3, 30)  # 最大30篇
            new_count = self.crawl_round(max_pages=pages, max_articles=articles)
            
            # 累计新增内容
            for key in total_new_content:
                total_new_content[key] += new_count.get(key, 0)
            
            # 评估（使用全部内容）
            print("\n  评估信息充分性...")
            eval_prompt = self.build_evaluation_prompt()
            
            # Token 估算（更精确）
            prompt_chars = len(eval_prompt)
            prompt_tokens = prompt_chars * 2  # 中文约2字符/token
            
            # 分项token统计
            articles_chars = sum(len(a.get('content', '')) for a in self.all_articles)
            discussions_chars = sum(len(d.get('content', '')) for d in self.all_discussions)
            news_chars = sum(len(n.get('title', '') + n.get('content', '')) for n in self.all_news)
            notices_chars = sum(len(n.get('title', '')) for n in self.all_notices)
            
            print(f"\n  📊 内容Token统计:")
            print(f"     文章: {len(self.all_articles)}篇, ~{articles_chars*2} tokens")
            print(f"     讨论: {len(self.all_discussions)}条, ~{discussions_chars*2} tokens")
            print(f"     资讯: {len(self.all_news)}条, ~{news_chars*2} tokens")
            print(f"     公告: {len(self.all_notices)}条, ~{notices_chars*2} tokens")
            print(f"     总计: ~{prompt_tokens} tokens")
            print(f"  Prompt 长度: {prompt_chars} 字符")
            
            eval_response = self.call_llm(eval_prompt, max_tokens=2000)
            
            # 解析结果
            evaluation_result = self.parse_evaluation_result(eval_response)
            
            if evaluation_result:
                print(f"\n  评估结果:")
                print(f"    总分: {evaluation_result.total_score}/200")
                print(f"    充分性: {evaluation_result.sufficiency}")
                print(f"    是否继续: {'是' if evaluation_result.need_more_crawl else '否'}")
                
                # 显示各主题评分
                print("\n  各主题评分:")
                for topic, data in evaluation_result.scores.items():
                    score = data.get('score', 0)
                    bar = '█' * (score // 5)
                    print(f"    {topic}: {score:2d}分 {bar}")
                
                # 决策：评分>=150即可终止
                if evaluation_result.total_score >= 150:
                    print("\n  ✅ 信息充分（>=150分），进入深度分析...")
                    break
                elif round_num >= max_rounds:
                    print("\n  ⚠️ 达到最大轮次，强制进入分析...")
                    break
                else:
                    print(f"\n  🔄 信息不足（{evaluation_result.total_score}/200 < 150），继续爬取...")
                    time.sleep(2)
            else:
                print("\n  ⚠️ 评估解析失败，继续下一轮...")
                time.sleep(2)
        
        # 深度分析
        print(f"\n{'='*60}")
        print("深度分析")
        print(f"{'='*60}")
        
        analysis_prompt = self.build_analysis_prompt()
        prompt_chars = len(analysis_prompt)
        
        # 详细内容统计
        print(f"\n  📊 送入分析模型的内容:")
        print(f"     文章: {len(self.all_articles)}篇")
        print(f"     讨论: {len(self.all_discussions)}条")
        print(f"     资讯: {len(self.all_news)}条")
        print(f"     公告: {len(self.all_notices)}条")
        print(f"     财务数据: {'已获取' if self.financial_data else '未获取'}")
        print(f"\n  Prompt 长度: {prompt_chars} 字符 (~{prompt_chars*2} tokens)")
        
        print("\n  调用 GLM-5 分析...")
        report = self.call_llm(analysis_prompt, max_tokens=8000)
        
        return {
            'symbol': self.symbol,
            'articles': self.all_articles,
            'discussions': self.all_discussions,
            'news': self.all_news,
            'notices': self.all_notices,
            'financial_data': self.financial_data,
            'evaluation': asdict(evaluation_result) if evaluation_result else None,
            'report': report,
            'stats': {
                'total_rounds': round_num,
                'total_content': total_new_content,
                'prompt_tokens': prompt_chars * 2
            }
        }


def generate_evaluation_report(result: dict) -> str:
    """生成包含爬取清单的评估报告"""
    from datetime import datetime
    
    eval_data = result.get('evaluation', {})
    symbol = result.get('symbol', 'UNKNOWN')
    
    report = f'''# {symbol} 信息充分性评估报告

**评估时间**: {datetime.now().strftime('%Y-%m-%d %H:%M')}
**股票代码**: {symbol}
**总分**: {eval_data.get('total_score', 0)}/200
**充分性**: {eval_data.get('sufficiency', '-')}

---

## 一、各主题评分详情

'''
    
    scores = eval_data.get('scores', {})
    for topic, sdata in scores.items():
        score = sdata.get('score', 0)
        reason = sdata.get('reason', '')
        evidence = sdata.get('evidence', '')
        bar = '█' * (score // 5)
        
        report += f'''### {topic} - {score}分 {bar}

**评分理由**: {reason}

**原文证据**: {evidence}

---

'''
    
    # 质量评估
    quality = eval_data.get('quality_assessment', {})
    report += f'''## 二、质量评估

| 维度 | 评估 |
|------|------|
| 信息来源可靠性 | {quality.get('source_reliability', '-')} |
| 观点多样性 | {quality.get('viewpoint_diversity', '-')} |
| 深度文章数 | {quality.get('deep_articles_count', '-')} 篇 |

'''
    
    # 覆盖分析
    coverage = eval_data.get('coverage_analysis', {})
    report += f'''## 三、内容覆盖分析

**优势领域**: {', '.join(coverage.get('strengths', []))}

**缺口领域**: {', '.join(coverage.get('gaps', [])) if coverage.get('gaps') else '无'}

'''
    
    # 爬取内容清单
    report += '''## 四、爬取内容清单

'''
    
    # 文章清单
    articles = result.get('articles', [])
    report += f'''### 专栏文章（{len(articles)}篇）

| # | 标题 | 作者 | 链接 |
|---|------|------|------|
'''
    for i, a in enumerate(articles, 1):
        title = a.get('title', '无标题')[:40]
        author = a.get('author', '未知')[:15]
        link = a.get('link', '')
        report += f'| {i} | {title}... | {author} | [查看]({link}) |\n'
    
    # 讨论清单
    discussions = result.get('discussions', [])
    report += f'''
### 热门讨论（{len(discussions)}条）

| # | 作者 | 内容摘要 | 链接 |
|---|------|----------|------|
'''
    for i, d in enumerate(discussions, 1):
        author = d.get('author', '未知')[:15]
        content = d.get('content', '')[:50]
        link = d.get('link', '')
        report += f'| {i} | {author} | {content}... | [查看]({link}) |\n'
    
    # 资讯清单
    news = result.get('news', [])
    report += f'''
### 相关资讯（{len(news)}条）

| # | 标题 | 时间 | 链接 |
|---|------|------|------|
'''
    for i, n in enumerate(news, 1):
        title = n.get('title', '无标题')[:40]
        time_str = n.get('time', '')
        link = n.get('link', '')
        report += f'| {i} | {title}... | {time_str} | [查看]({link}) |\n'
    
    # 公告清单
    notices = result.get('notices', [])
    report += f'''
### 公告（{len(notices)}条）

| # | 标题 | 链接 |
|---|------|------|
'''
    for i, n in enumerate(notices, 1):
        title = n.get('title', '公告')[:50]
        link = n.get('link', '')
        report += f'| {i} | {title} | [查看]({link}) |\n'
    
    # 爬取建议
    crawl = eval_data.get('crawl_suggestions', {})
    report += f'''
## 五、爬取建议

| 项目 | 建议 |
|------|------|
| 是否需要继续爬取 | {'否' if not eval_data.get('need_more_crawl', True) else '是'} |
| 优先类型 | {', '.join(crawl.get('priority', []))} |
| 关注主题 | {', '.join(crawl.get('focus_topics', [])) if crawl.get('focus_topics') else '无'} |
| 原因 | {crawl.get('reason', '-')} |

---

**结论**: 总分 {eval_data.get('total_score', 0)}/200，{eval_data.get('sufficiency', '')}，进入深度分析阶段。
'''
    
    return report


def generate_evaluation_report(result: dict) -> str:
    """生成包含爬取清单的评估报告"""
    from datetime import datetime
    
    eval_data = result.get('evaluation', {})
    symbol = result.get('symbol', 'UNKNOWN')
    
    report = f'''# {symbol} 信息充分性评估报告

**评估时间**: {datetime.now().strftime('%Y-%m-%d %H:%M')}
**股票代码**: {symbol}
**总分**: {eval_data.get('total_score', 0)}/200
**充分性**: {eval_data.get('sufficiency', '-')}

---

## 一、各主题评分详情

'''
    
    scores = eval_data.get('scores', {})
    for topic, sdata in scores.items():
        score = sdata.get('score', 0)
        reason = sdata.get('reason', '')
        evidence = sdata.get('evidence', '')
        bar = '█' * (score // 5)
        
        report += f'''### {topic} - {score}分 {bar}

**评分理由**: {reason}

**原文证据**: {evidence}

---

'''
    
    # 质量评估
    quality = eval_data.get('quality_assessment', {})
    report += f'''## 二、质量评估

| 维度 | 评估 |
|------|------|
| 信息来源可靠性 | {quality.get('source_reliability', '-')} |
| 观点多样性 | {quality.get('viewpoint_diversity', '-')} |
| 深度文章数 | {quality.get('deep_articles_count', '-')} 篇 |

'''
    
    # 覆盖分析
    coverage = eval_data.get('coverage_analysis', {})
    report += f'''## 三、内容覆盖分析

**优势领域**: {', '.join(coverage.get('strengths', []))}

**缺口领域**: {', '.join(coverage.get('gaps', [])) if coverage.get('gaps') else '无'}

'''
    
    # 爬取内容清单
    report += '''## 四、爬取内容清单

'''
    
    # 文章清单
    articles = result.get('articles', [])
    report += f'''### 专栏文章（{len(articles)}篇）

| # | 标题 | 作者 | 链接 |
|---|------|------|------|
'''
    for i, a in enumerate(articles, 1):
        title = a.get('title', '无标题')[:40]
        author = a.get('author', '未知')[:15]
        link = a.get('link', '')
        report += f'| {i} | {title}... | {author} | [查看]({link}) |\n'
    
    # 讨论清单
    discussions = result.get('discussions', [])
    report += f'''
### 热门讨论（{len(discussions)}条）

| # | 作者 | 内容摘要 | 链接 |
|---|------|----------|------|
'''
    for i, d in enumerate(discussions, 1):
        author = d.get('author', '未知')[:15]
        content = d.get('content', '')[:50]
        link = d.get('link', '')
        report += f'| {i} | {author} | {content}... | [查看]({link}) |\n'
    
    # 资讯清单
    news = result.get('news', [])
    report += f'''
### 相关资讯（{len(news)}条）

| # | 标题 | 时间 | 链接 |
|---|------|------|------|
'''
    for i, n in enumerate(news, 1):
        title = n.get('title', '无标题')[:40]
        time_str = n.get('time', '')
        link = n.get('link', '')
        report += f'| {i} | {title}... | {time_str} | [查看]({link}) |\n'
    
    # 公告清单
    notices = result.get('notices', [])
    report += f'''
### 公告（{len(notices)}条）

| # | 标题 | 链接 |
|---|------|------|
'''
    for i, n in enumerate(notices, 1):
        title = n.get('title', '公告')[:50]
        link = n.get('link', '')
        report += f'| {i} | {title} | [查看]({link}) |\n'
    
    # 爬取建议
    crawl = eval_data.get('crawl_suggestions', {})
    report += f'''
## 五、爬取建议

| 项目 | 建议 |
|------|------|
| 是否需要继续爬取 | {'否' if not eval_data.get('need_more_crawl', True) else '是'} |
| 优先类型 | {', '.join(crawl.get('priority', []))} |
| 关注主题 | {', '.join(crawl.get('focus_topics', [])) if crawl.get('focus_topics') else '无'} |
| 原因 | {crawl.get('reason', '-')} |

---

**结论**: 总分 {eval_data.get('total_score', 0)}/200，{eval_data.get('sufficiency', '')}，进入深度分析阶段。
'''
    
    return report


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='智能迭代爬取系统 V2')
    parser.add_argument('symbol', help='股票代码')
    parser.add_argument('--max-rounds', type=int, default=10, help='最大轮次（默认10）')
    parser.add_argument('--output', '-o', help='输出目录')
    
    args = parser.parse_args()
    
    crawler = SmartCrawlerV2(args.symbol)
    result = crawler.run(max_rounds=args.max_rounds)
    
    # 保存报告
    output_dir = Path(args.output) if args.output else Path(__file__).parent.parent / 'data' / 'reports'
    output_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = time.strftime('%Y%m%d_%H%M%S')
    
    # 保存报告
    report_path = output_dir / f'{args.symbol}_smart_v2_report_{timestamp}.md'
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(result['report'])
    print(f"\n  报告已保存: {report_path}")
    
    # 生成并保存评估报告（含爬取清单）
    if result.get('evaluation'):
        eval_report = generate_evaluation_report(result)
        eval_path = output_dir / f'{args.symbol}_evaluation_{timestamp}.md'
        with open(eval_path, 'w', encoding='utf-8') as f:
            f.write(eval_report)
        print(f"  评估报告已保存: {eval_path}")
    
    # 保存完整数据（含爬取内容清单）
    data_path = output_dir / f'{args.symbol}_smart_v2_data_{timestamp}.json'
    
    # 构建完整数据（含爬取内容清单）
    full_data = {
        'symbol': result['symbol'],
        'evaluation': result.get('evaluation'),
        'financial_data': result.get('financial_data'),
        'articles': result.get('articles', []),
        'discussions': result.get('discussions', []),
        'news': result.get('news', []),
        'notices': result.get('notices', []),
        'articles_count': len(result.get('articles', [])),
        'discussions_count': len(result.get('discussions', [])),
        'news_count': len(result.get('news', [])),
        'notices_count': len(result.get('notices', []))
    }
    
    with open(data_path, 'w', encoding='utf-8') as f:
        json.dump(full_data, f, ensure_ascii=False, indent=2)
    print(f"  数据已保存: {data_path}")


if __name__ == '__main__':
    main()