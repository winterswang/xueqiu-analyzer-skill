#!/usr/bin/env python3
"""
雪球公司分析报告生成器

功能：
- 调用 GLM-5 分析股票数据
- 生成结构化投资分析报告
"""

import os
import sys
import json
import urllib.request
import urllib.error
from datetime import datetime
from typing import Dict, List, Optional


class GLM5Analyzer:
    """GLM-5 分析器"""
    
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.environ.get('BAILIAN_API_KEY', '')
        self.api_url = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
        
    def analyze(self, prompt: str, max_tokens: int = 4000) -> str:
        """调用 GLM-5 API"""
        if not self.api_key:
            raise ValueError("未配置 BAILIAN_API_KEY")
        
        data = {
            "model": "glm-5",
            "messages": [
                {"role": "system", "content": "你是一位专业的投资分析助手，擅长分析股票投资价值。请用中文回答，输出结构化的分析报告。"},
                {"role": "user", "content": prompt}
            ],
            "max_tokens": max_tokens,
            "temperature": 0.7
        }
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        req = urllib.request.Request(
            self.api_url,
            data=json.dumps(data).encode('utf-8'),
            headers=headers,
            method='POST'
        )
        
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                result = json.loads(resp.read().decode('utf-8'))
                return result['choices'][0]['message']['content']
        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8') if e.fp else ''
            raise Exception(f"API 请求失败 ({e.code}): {error_body}")
        except Exception as e:
            raise Exception(f"API 调用异常: {e}")


class ReportGenerator:
    """报告生成器"""
    
    def __init__(self, api_key: str = None):
        self.analyzer = GLM5Analyzer(api_key)
    
    def generate(self, stock_data: dict) -> str:
        """
        生成投资分析报告
        
        Args:
            stock_data: 股票数据 (来自 stock_crawler)
            
        Returns:
            Markdown 格式的分析报告
        """
        symbol = stock_data.get('symbol', '')
        name = stock_data.get('name', '')
        price = stock_data.get('price', '')
        discussions = stock_data.get('discussions', [])
        news = stock_data.get('news', [])
        notices = stock_data.get('notices', [])
        articles = stock_data.get('articles', [])  # 新增：专栏文章
        
        # 构建 prompt
        prompt = self._build_prompt(symbol, name, price, discussions, news, articles)
        
        # 调用 GLM-5 分析
        print(f"正在调用 GLM-5 分析 {symbol}...")
        analysis = self.analyzer.analyze(prompt, max_tokens=4000)
        
        # 构建完整报告
        report = self._format_report(symbol, name, price, discussions, news, notices, articles, analysis)
        
        return report
    
    def _build_prompt(self, symbol: str, name: str, price: str, 
                      discussions: list, news: list, articles: list = None) -> str:
        """构建分析 prompt - 严格按照需求文档模板"""
        
        # 讨论内容 - 表格格式
        discussion_table = "| 作者 | 观点摘要 | 时间 |\n|------|----------|------|\n"
        for d in discussions[:5]:
            author = d.get('author', '未知')[:15]
            content = d.get('content', '')[:50].replace('\n', ' ')
            time_str = d.get('time', '')
            discussion_table += f"| {author} | {content}... | {time_str} |\n"
        
        # 资讯内容 - 表格格式
        news_table = "| 标题 | 时间 |\n|------|------|\n"
        for n in news[:5]:
            title = n.get('title', '')[:40]
            time_str = n.get('time', '')
            news_table += f"| {title} | {time_str} |\n"
        
        # 文章内容 - 用于深度分析
        articles_text = ""
        if articles:
            for i, a in enumerate(articles[:3], 1):
                articles_text += f"""
### 文章 {i}: {a.get('title', '无标题')}

**作者**: {a.get('author', '未知')}  
**链接**: {a.get('link', '')}  
**时间**: {a.get('time', '')}

**正文内容**:
{a.get('content', '')[:2000]}

---

"""
        
        prompt = f"""
请分析以下股票的投资价值，**严格按照下面的模板格式输出报告**。

## 股票基本信息
- 代码: {symbol}
- 名称: {name}
- 价格信息: {price}

## 雪球讨论（投资者观点）
{discussion_table}

## 专栏文章（深度分析）
{articles_text if articles_text else '暂无专栏文章'}

## 相关资讯
{news_table}

---

**请严格按照以下模板格式输出报告，不要改变结构：**

# {name or symbol}({symbol})投资价值分析报告

**分析日期：[日期]**
**分析模型：智谱 GLM-5**

---

## 📊 执行摘要

### 核心结论

**估值判断**：[合理/低估/高估，并说明理由]

**投资建议**：[买入/观望/卖出]，建议仓位 [X]%

**核心逻辑**：
- 逻辑1：[详细说明]
- 逻辑2：[详细说明]

**关键风险**：[最大的风险点]

---

## 一、基本信息

| 指标 | 数值 |
|------|------|
| 股票代码 | {symbol} |
| 股票名称 | {name or '-'} |
| 当前价 | {price or '-'} |

---

## 二、雪球讨论分析

### 2.1 热门讨论（来自股票详情页）

[分析讨论中的主要观点、多空情绪、市场关注点]

### 2.2 深度文章分析

**重要：请引用文章原文内容进行分析，使用以下格式：**

> 📌 **引用自文章《文章标题》**：
> "{{引用原文关键段落}}"

**分析**：[对该文章内容的分析和解读]

---

## 三、资讯动态

[分析重要新闻及对股价的影响]

---

## 四、财务数据

> 注：暂未接入财务数据源，建议结合财报分析

---

## 五、价格趋势

> 注：暂未接入K线数据源，建议结合技术分析

---

## 六、投资建议

| 操作 | 建议 |
|------|------|
| 建仓时机 | [建议] |
| 仓位控制 | [X]% |
| 止损线 | [价格或比例] |

---

**风险提示：本报告仅供参考，不构成投资建议。投资有风险，入市需谨慎。**

---

**重要提示**：
1. 请完全按照上述模板格式输出
2. 在"深度文章分析"部分，必须引用文章原文内容
3. 引用格式：> 📌 **引用自文章《标题》**："原文内容"
"""
        return prompt
    
    def _format_report(self, symbol: str, name: str, price: str,
                       discussions: list, news: list, notices: list,
                       articles: list, analysis: str) -> str:
        """格式化完整报告 - 直接返回 GLM-5 按模板生成的分析"""
        # GLM-5 已经按照模板格式输出了，直接使用
        # 只在末尾添加数据来源说明
        report = analysis
        
        # 添加数据来源
        report += f"""

---

## 📋 数据来源

- 雪球讨论: {len(discussions)} 条
- 专栏文章: {len(articles)} 篇
- 相关资讯: {len(news)} 条
- 公告链接: {len(notices)} 条
"""
        return report


def main():
    """测试"""
    import argparse
    
    parser = argparse.ArgumentParser(description='雪球公司分析报告生成器')
    parser.add_argument('--input', '-i', required=True, help='股票数据 JSON 文件')
    parser.add_argument('--output', '-o', help='输出报告文件')
    
    args = parser.parse_args()
    
    # 读取股票数据
    with open(args.input, 'r', encoding='utf-8') as f:
        stock_data = json.load(f)
    
    # 生成报告
    generator = ReportGenerator()
    report = generator.generate(stock_data)
    
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(report)
        print(f"报告已保存到: {args.output}")
    else:
        print(report)


if __name__ == '__main__':
    main()