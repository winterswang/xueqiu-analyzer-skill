#!/usr/bin/env python3
"""
雪球公司分析全流程 V2

流程：
1. 爬取股票数据（讨论、资讯、公告、文章）
2. 获取财务数据（雪球 API + AkShare）
3. 生成分析报告
4. 保存并同步 Gist
"""

import os
import sys
import json
import argparse
from datetime import datetime
from pathlib import Path

# 添加脚本目录到 path
script_dir = Path(__file__).parent
sys.path.insert(0, str(script_dir))

from stock_crawler_v2 import XueqiuStockCrawlerV2
from financial_fetcher import FinancialDataFetcher
from report_generator import ReportGenerator


def run_full_analysis(symbol: str, max_discussions: int = 20, max_news: int = 20, 
                      max_articles: int = 10, max_pages: int = 3, output_dir: str = None):
    """
    运行全流程分析
    
    Args:
        symbol: 股票代码
        max_discussions: 最大讨论数
        max_news: 最大资讯数
        max_articles: 最大文章数
        max_pages: 最大分页数
        output_dir: 输出目录
    """
    print(f"\n{'='*60}")
    print(f"雪球公司分析 V2 - 全流程")
    print(f"股票代码: {symbol}")
    print(f"{'='*60}\n")
    
    # 设置输出目录
    if output_dir is None:
        output_dir = script_dir.parent / 'data' / 'reports'
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # ========== 步骤 1: 爬取股票数据 ==========
    print(f"\n[步骤 1/4] 爬取股票数据...")
    print(f"  - 最大讨论数: {max_discussions}")
    print(f"  - 最大资讯数: {max_news}")
    print(f"  - 最大文章数: {max_articles}")
    print(f"  - 最大分页数: {max_pages}")
    
    crawler = XueqiuStockCrawlerV2(headless=True)
    stock_info = crawler.crawl(
        symbol=symbol,
        max_discussions=max_discussions,
        max_news=max_news,
        max_articles=max_articles,
        max_scrolls=max_pages
    )
    
    stock_data = crawler.to_dict(stock_info)
    
    # ========== 步骤 2: 获取财务数据 ==========
    print(f"\n[步骤 2/4] 获取财务数据...")
    
    financial_fetcher = FinancialDataFetcher()
    
    # 读取 cookies 文件
    cookies_path = script_dir.parent / 'config' / 'xueqiu_cookies.json'
    cookies = None
    if cookies_path.exists():
        with open(cookies_path, 'r') as f:
            cookies = json.load(f)
    
    financial_data = financial_fetcher.fetch(symbol, cookies)
    
    if financial_data:
        stock_data['financial_data'] = financial_fetcher.to_dict(financial_data)
        print(f"  ✅ 财务数据获取成功")
        print(f"     PE: {financial_data.pe_ttm:.1f}")
        print(f"     PB: {financial_data.pb:.1f}")
        print(f"     ROE: {financial_data.roe:.1f}%")
        print(f"     市值: {financial_data.market_cap/1e9:.1f}B")
        print(f"     52周区间: {financial_data.low52w:.1f} - {financial_data.high52w:.1f}")
    else:
        print(f"  ⚠️ 财务数据获取失败")
    
    # 保存原始数据
    data_file = output_dir / f'{symbol}_data_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
    with open(data_file, 'w', encoding='utf-8') as f:
        json.dump(stock_data, f, ensure_ascii=False, indent=2)
    print(f"\n原始数据已保存: {data_file}")
    
    # ========== 步骤 3: 生成分析报告 ==========
    print(f"\n[步骤 3/4] 生成分析报告...")
    
    generator = ReportGenerator()
    report = generator.generate(stock_data)
    
    # 保存报告
    report_file = output_dir / f'{symbol}_report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.md'
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(report)
    print(f"\n分析报告已保存: {report_file}")
    
    # ========== 步骤 4: 输出摘要 ==========
    print(f"\n[步骤 4/4] 输出摘要...")
    print(f"\n{'='*60}")
    print(f"分析完成!")
    print(f"{'='*60}")
    print(f"  股票: {stock_info.name} ({symbol})")
    print(f"  讨论: {len(stock_info.discussions)} 条")
    print(f"  资讯: {len(stock_info.news)} 条")
    print(f"  公告: {len(stock_info.notices)} 条")
    print(f"  文章: {len(stock_info.articles)} 篇")
    
    if financial_data:
        print(f"\n  财务数据:")
        print(f"    PE: {financial_data.pe_ttm:.1f}")
        print(f"    PB: {financial_data.pb:.1f}")
        print(f"    ROE: {financial_data.roe:.1f}%")
        print(f"    52周高低: {financial_data.low52w:.1f} - {financial_data.high52w:.1f}")
    
    print(f"\n  原始数据: {data_file}")
    print(f"  分析报告: {report_file}")
    print(f"{'='*60}\n")
    
    return report_file


def main():
    parser = argparse.ArgumentParser(description='雪球公司分析全流程 V2')
    parser.add_argument('symbol', help='股票代码 (如 TCOM, APP)')
    parser.add_argument('--max-discussions', type=int, default=20, help='最大讨论数')
    parser.add_argument('--max-news', type=int, default=20, help='最大资讯数')
    parser.add_argument('--max-articles', type=int, default=10, help='最大文章数')
    parser.add_argument('--max-pages', type=int, default=3, help='最大分页数')
    parser.add_argument('--output', '-o', help='输出目录')
    
    args = parser.parse_args()
    
    run_full_analysis(
        symbol=args.symbol,
        max_discussions=args.max_discussions,
        max_news=args.max_news,
        max_articles=args.max_articles,
        max_pages=args.max_pages,
        output_dir=args.output
    )


if __name__ == '__main__':
    main()