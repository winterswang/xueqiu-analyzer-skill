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
        
        # 构建 prompt
        prompt = self._build_prompt(symbol, name, price, discussions, news)
        
        # 调用 GLM-5 分析
        print(f"正在调用 GLM-5 分析 {symbol}...")
        analysis = self.analyzer.analyze(prompt, max_tokens=4000)
        
        # 构建完整报告
        report = self._format_report(symbol, name, price, discussions, news, notices, analysis)
        
        return report
    
    def _build_prompt(self, symbol: str, name: str, price: str, 
                      discussions: list, news: list) -> str:
        """构建分析 prompt"""
        
        # 讨论内容
        discussion_text = ""
        for i, d in enumerate(discussions[:5], 1):
            discussion_text += f"\n### 讨论 {i}\n"
            discussion_text += f"作者: {d.get('author', '未知')}\n"
            discussion_text += f"时间: {d.get('time', '')}\n"
            discussion_text += f"内容: {d.get('content', '')[:300]}\n"
        
        # 资讯内容
        news_text = ""
        for i, n in enumerate(news[:5], 1):
            news_text += f"\n{i}. {n.get('title', '')} ({n.get('time', '')})\n"
        
        prompt = f"""
请分析以下股票的投资价值，生成结构化的投资分析报告。

## 股票基本信息
- 代码: {symbol}
- 名称: {name}
- 价格信息: {price}

## 雪球讨论（投资者观点）
{discussion_text}

## 相关资讯
{news_text}

请从以下维度进行分析，以 Markdown 格式输出：

### 一、执行摘要
- 核心结论（估值判断、投资建议）
- 关键逻辑（2-3 点）
- 主要风险

### 二、投资者观点分析
- 多空观点对比
- 主要关注点
- 市场情绪判断

### 三、资讯要点
- 重要新闻摘要
- 对股价的可能影响

### 四、综合评估
- 优势
- 风险
- 关注要点

### 五、投资建议
- 操作建议
- 仓位建议
- 止损止盈参考

注意：
1. 基于提供的信息进行客观分析
2. 不确定的要明确说明
3. 在报告末尾添加风险提示
"""
        return prompt
    
    def _format_report(self, symbol: str, name: str, price: str,
                       discussions: list, news: list, notices: list,
                       analysis: str) -> str:
        """格式化完整报告"""
        
        report = f"""# {name or symbol} 投资价值分析报告

**分析日期**: {datetime.now().strftime('%Y-%m-%d %H:%M')}
**分析模型**: 智谱 GLM-5
**股票代码**: {symbol}

---

## 📊 基本信息

| 指标 | 数值 |
|------|------|
| 股票名称 | {name or '-'} |
| 股票代码 | {symbol} |
| 价格信息 | {price or '-'} |

---

## 🤖 GLM-5 深度分析

{analysis}

---

## 📋 数据来源

- 雪球讨论: {len(discussions)} 条
- 相关资讯: {len(news)} 条
- 公告链接: {len(notices)} 条

---

**风险提示**: 本报告仅供参考，不构成投资建议。投资有风险，入市需谨慎。
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