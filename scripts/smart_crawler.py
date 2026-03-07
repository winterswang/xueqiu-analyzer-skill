#!/usr/bin/env python3
"""
智能迭代爬取系统

架构：
1. 第一阶段：爬取 → 评估（Prompt 1）→ 决定是否继续
2. 第二阶段：深度分析（Prompt 2）→ 报告

特点：
- 利用 LLM 判断信息充分性
- 最多 3 轮迭代
- 充分利用 128K 上下文进行深度分析
"""

import os
import sys
import json
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from stock_crawler_v2 import XueqiuStockCrawlerV2
from financial_fetcher import FinancialDataFetcher


class SmartIterativeCrawler:
    """智能迭代爬取系统"""
    
    # 分析框架需要的主题
    ANALYSIS_FRAMEWORK = {
        "估值分析": ["估值", "PE", "PB", "市值", "价格"],
        "商业模式": ["商业模式", "护城河", "竞争优势", "壁垒"],
        "财务质量": ["现金流", "利润", "营收", "ROE", "毛利"],
        "竞争格局": ["竞争", "对手", "美团", "京东", "飞猪"],
        "管理层": ["管理层", "CEO", "高管", "战略", "治理"],
        "风险因素": ["风险", "AI", "反垄断", "监管", "调查"],
        "用户价值": ["用户", "客户", "体验", "服务"],
        "未来前景": ["增长", "国际化", "入境游", "前景"]
    }
    
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.all_articles = []
        self.all_discussions = []
        self.all_news = []
        self.seen_links = set()
        self.cookies = None
        
    def crawl_round(self, max_pages: int = 3, max_articles: int = 10) -> dict:
        """执行一轮爬取"""
        crawler = XueqiuStockCrawlerV2(headless=True)
        
        result = crawler.crawl(
            symbol=self.symbol,
            max_discussions=30,
            max_news=30,
            max_articles=max_articles,
            max_scrolls=max_pages
        )
        
        data = crawler.to_dict(result)
        self.cookies = data.get('cookies', self.cookies)
        
        # 合并数据（去重）
        new_count = {'articles': 0, 'discussions': 0, 'news': 0}
        
        for a in data.get('articles', []):
            link = a.get('link', '')
            if link and link not in self.seen_links:
                self.seen_links.add(link)
                self.all_articles.append(a)
                new_count['articles'] += 1
        
        for d in data.get('discussions', []):
            link = d.get('link', '')
            if link and link not in self.seen_links:
                self.seen_links.add(link)
                self.all_discussions.append(d)
                new_count['discussions'] += 1
        
        for n in data.get('news', []):
            link = n.get('link', '')
            if link and link not in self.seen_links:
                self.seen_links.add(link)
                self.all_news.append(n)
                new_count['news'] += 1
        
        return new_count
    
    def build_evaluation_prompt(self) -> str:
        """构建评估 Prompt（Prompt 1）"""
        
        # 汇总当前内容
        content_summary = []
        
        # 文章摘要
        content_summary.append("## 专栏文章")
        for i, a in enumerate(self.all_articles[:15], 1):
            title = a.get('title', '无标题')[:50]
            content = a.get('content', '')[:200]
            content_summary.append(f"{i}. {title}")
            content_summary.append(f"   摘要: {content}...")
        
        # 讨论摘要
        content_summary.append("\n## 热门讨论")
        for i, d in enumerate(self.all_discussions[:15], 1):
            content = d.get('content', '')[:100]
            content_summary.append(f"{i}. {content}...")
        
        content_text = '\n'.join(content_summary)
        
        # 分析框架
        framework_text = '\n'.join([
            f"- {category}: {', '.join(keywords)}"
            for category, keywords in self.ANALYSIS_FRAMEWORK.items()
        ])
        
        prompt = f"""你是一位专业的投资研究分析师。请评估以下信息是否足够支撑一份高质量的投资分析报告。

# 分析框架要求

{framework_text}

# 当前收集的信息

{content_text}

# 评估任务

请评估以上信息是否充分，输出以下内容：

## 1. 充分性评分
- 总体评分（0-100分）
- 每个主题的覆盖程度评分

## 2. 缺失分析
- 缺失的主题有哪些？
- 哪些主题需要更多内容支撑？

## 3. 爬取建议
- 是否需要继续爬取？（是/否）
- 如果需要，建议爬取哪些类型的内容？（讨论/专栏/资讯/公告）

## 4. 质量评估
- 当前内容的整体质量如何？
- 有多少篇深度分析文章（>=500字）？
- 讨论的观点是否多元？

请以 JSON 格式输出：
```json
{{
  "sufficiency_score": 75,
  "topic_scores": {{
    "估值分析": 80,
    "商业模式": 60,
    ...
  }},
  "missing_topics": ["管理层", "未来前景"],
  "need_more_crawl": true,
  "crawl_suggestions": ["讨论", "专栏"],
  "quality_assessment": "当前有3篇深度文章，观点多元但缺少管理层分析",
  "deep_articles_count": 3
}}
```
"""
        return prompt
    
    def build_analysis_prompt(self, financial_data: dict) -> str:
        """构建深度分析 Prompt（Prompt 2）"""
        
        # 完整内容
        content_parts = []
        
        # 文章完整内容
        content_parts.append("=" * 60)
        content_parts.append("专栏文章（完整内容）")
        content_parts.append("=" * 60)
        
        for i, a in enumerate(self.all_articles, 1):
            title = a.get('title', '无标题')
            author = a.get('author', '未知')
            content = a.get('content', '')
            link = a.get('link', '')
            
            content_parts.append(f"\n### 文章 {i}: {title}")
            content_parts.append(f"作者: {author}")
            content_parts.append(f"链接: {link}")
            content_parts.append(f"\n{content}\n")
            content_parts.append("-" * 40)
        
        # 讨论内容
        content_parts.append("\n" + "=" * 60)
        content_parts.append("热门讨论")
        content_parts.append("=" * 60)
        
        for i, d in enumerate(self.all_discussions[:20], 1):
            content = d.get('content', '')
            author = d.get('author', '未知')
            content_parts.append(f"\n[{i}] {author}: {content}")
        
        content_text = '\n'.join(content_parts)
        
        # 财务数据
        fin_text = ""
        if financial_data:
            fin_text = f"""
## 财务数据

| 指标 | 数值 |
|------|------|
| PE | {financial_data.get('pe_ttm', 0):.1f} |
| PB | {financial_data.get('pb', 0):.1f} |
| ROE | {financial_data.get('roe', 0):.1f}% |
| 毛利率 | {financial_data.get('gross_margin', 0):.1f}% |
| 净利率 | {financial_data.get('net_margin', 0):.1f}% |
| 营收增速 | {financial_data.get('revenue_growth', 0):.1f}% |
| 利润增速 | {financial_data.get('profit_growth', 0):.1f}% |
| 52周高低 | {financial_data.get('low52w', 0):.1f} - {financial_data.get('high52w', 0):.1f} |
"""
        
        prompt = f"""你是一位专业的价值投资分析师，擅长深度分析上市公司投资价值。

请基于以下详实的信息，输出一份高质量的投资分析报告。

{content_text}

{fin_text}

# 分析要求

请严格按照以下结构输出报告：

## 一、执行摘要（核心结论）

### 估值判断
- 当前估值是否合理？
- 支持判断的关键证据

### 投资建议
- 买入/观望/卖出
- 建议仓位
- 建仓时机

### 核心逻辑（3-5条）
- 每条逻辑必须有原文引用支撑

### 关键风险
- 最大的风险点是什么？

## 二、深度分析

### 2.1 商业模式与护城河
- 引用原文分析
- 护城河是否牢固？

### 2.2 竞争格局
- 主要竞争对手
- 竞争优势与劣势

### 2.3 管理层与治理
- 管理层质量评估
- 公司治理状况

### 2.4 财务质量
- 盈利能力分析
- 现金流质量

### 2.5 未来前景
- 增长动力
- 国际化机会

## 三、投资决策

### 入场条件
- 什么价格可以买入？

### 跟踪指标
- 需要持续关注哪些指标？

### 退出条件
- 什么情况下卖出？

# 重要提示

1. **必须引用原文**：每个关键观点都要标注来源，格式：> 📌 引用自《文章标题》："原文内容"
2. **定量分析**：尽量使用具体数字，避免模糊表述
3. **多空平衡**：既要分析利好，也要分析风险
4. **可操作性**：投资建议要具体、可执行

请充分利用所有提供的信息，进行深度分析。
"""
        return prompt
    
    def call_llm(self, prompt: str, max_tokens: int = 4000) -> str:
        """调用 LLM"""
        import urllib.request
        
        # 从 openclaw.json 读取配置
        config_path = os.path.expanduser('~/.openclaw/openclaw.json')
        with open(config_path, 'r') as f:
            config = json.load(f)
        
        provider = config.get('models', {}).get('providers', {}).get('qwencode', {})
        api_key = provider.get('apiKey', '')
        base_url = provider.get('baseUrl', '')
        
        data = {
            "model": "glm-5",
            "messages": [
                {"role": "user", "content": prompt}
            ],
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
        
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode('utf-8'))
            return result['choices'][0]['message']['content']
    
    def run(self, max_rounds: int = 3) -> dict:
        """执行智能迭代爬取"""
        print(f"\n{'='*60}")
        print(f"智能迭代爬取系统: {self.symbol}")
        print(f"{'='*60}\n")
        
        # 读取 cookies
        cookies_path = Path(__file__).parent.parent / 'config' / 'xueqiu_cookies.json'
        if cookies_path.exists():
            with open(cookies_path, 'r') as f:
                self.cookies = json.load(f)
        
        for round_num in range(1, max_rounds + 1):
            print(f"\n--- 第 {round_num} 轮 ---")
            
            # 爬取
            pages = 3 + round_num * 2  # 每轮增加页数
            new_count = self.crawl_round(max_pages=pages, max_articles=15)
            
            print(f"新增: {new_count['articles']} 文章, {new_count['discussions']} 讨论, {new_count['news']} 资讯")
            print(f"累计: {len(self.all_articles)} 文章, {len(self.all_discussions)} 讨论")
            
            # 评估
            print("\n评估信息充分性...")
            eval_prompt = self.build_evaluation_prompt()
            eval_result = self.call_llm(eval_prompt, max_tokens=2000)
            
            print(f"\n评估结果:\n{eval_result[:500]}...")
            
            # 解析评估结果
            try:
                # 提取 JSON
                import re
                json_match = re.search(r'```json\s*(.*?)\s*```', eval_result, re.DOTALL)
                if json_match:
                    eval_json = json.loads(json_match.group(1))
                    score = eval_json.get('sufficiency_score', 0)
                    need_more = eval_json.get('need_more_crawl', False)
                    
                    print(f"\n充分性评分: {score}/100")
                    print(f"是否需要继续: {'是' if need_more else '否'}")
                    
                    if score >= 70 or not need_more:
                        print("\n✅ 信息充分，开始深度分析...")
                        break
            except Exception as e:
                print(f"解析评估结果失败: {e}")
            
            time.sleep(2)
        
        # 获取财务数据
        print("\n获取财务数据...")
        fetcher = FinancialDataFetcher()
        financial_data = fetcher.fetch(self.symbol, self.cookies)
        fin_dict = fetcher.to_dict(financial_data) if financial_data else {}
        
        # 深度分析
        print("\n生成深度分析报告...")
        analysis_prompt = self.build_analysis_prompt(fin_dict)
        report = self.call_llm(analysis_prompt, max_tokens=8000)
        
        return {
            'symbol': self.symbol,
            'articles': self.all_articles,
            'discussions': self.all_discussions,
            'news': self.all_news,
            'financial_data': fin_dict,
            'report': report
        }


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='智能迭代爬取系统')
    parser.add_argument('symbol', help='股票代码')
    parser.add_argument('--max-rounds', type=int, default=3, help='最大轮次')
    
    args = parser.parse_args()
    
    crawler = SmartIterativeCrawler(args.symbol)
    result = crawler.run(max_rounds=args.max_rounds)
    
    # 保存报告
    report_path = f'data/reports/{args.symbol}_smart_report.md'
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(result['report'])
    
    print(f"\n报告已保存: {report_path}")


if __name__ == '__main__':
    main()