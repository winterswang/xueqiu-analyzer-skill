#!/usr/bin/env python3
"""
雪球公司分析 Skill - 主入口

用法:
    python analyzer.py APP
    python analyzer.py APP --output report.md
"""

import os
import sys
import json
import argparse
from datetime import datetime
from pathlib import Path

# 添加脚本目录到 path
sys.path.insert(0, str(Path(__file__).parent))

from stock_crawler import XueqiuStockCrawler
from report_generator import ReportGenerator


class XueqiuAnalyzer:
    """雪球公司分析器"""
    
    def __init__(self, api_key: str = None, headless: bool = True):
        self.crawler = XueqiuStockCrawler(headless=headless)
        self.report_generator = ReportGenerator(api_key=api_key)
    
    def analyze(self, symbol: str, max_discussions: int = 10, max_news: int = 10) -> str:
        """
        分析股票
        
        Args:
            symbol: 股票代码
            max_discussions: 最大讨论数
            max_news: 最大资讯数
            
        Returns:
            Markdown 格式的分析报告
        """
        print(f"\n{'='*60}")
        print(f"雪球公司分析 - {symbol}")
        print(f"{'='*60}\n")
        
        # 1. 爬取数据
        print("📌 步骤 1/2: 爬取股票数据...")
        stock_info = self.crawler.crawl(
            symbol=symbol,
            max_discussions=max_discussions,
            max_news=max_news,
            max_articles=5  # 新增：爬取5篇专栏文章
        )
        stock_data = self.crawler.to_dict(stock_info)
        
        print(f"  ✅ 获取 {len(stock_data['discussions'])} 条讨论")
        print(f"  ✅ 获取 {len(stock_data.get('articles', []))} 篇文章")
        print(f"  ✅ 获取 {len(stock_data['news'])} 条资讯")
        print(f"  ✅ 获取 {len(stock_data['notices'])} 条公告")
        
        # 2. 生成报告
        print("\n📌 步骤 2/2: 生成分析报告...")
        report = self.report_generator.generate(stock_data)
        
        print("\n✅ 分析完成!\n")
        
        return report
    
    def analyze_and_save(self, symbol: str, output_path: str = None, 
                         max_discussions: int = 10, max_news: int = 10) -> str:
        """分析并保存报告"""
        report = self.analyze(symbol, max_discussions, max_news)
        
        if output_path:
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(report)
            print(f"📄 报告已保存: {output_path}\n")
        else:
            # 默认保存到 data 目录
            data_dir = Path(__file__).parent.parent / 'data'
            data_dir.mkdir(parents=True, exist_ok=True)
            
            filename = f"{symbol}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
            filepath = data_dir / filename
            
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(report)
            print(f"📄 报告已保存: {filepath}\n")
        
        return report


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description='雪球公司分析 Skill',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python analyzer.py APP              # 分析 APP (Applovin)
  python analyzer.py TCOM -o report.md  # 分析携程并保存到指定文件
  python analyzer.py 600519           # 分析贵州茅台 (A股)
        """
    )
    
    parser.add_argument('symbol', help='股票代码 (如 APP, TCOM, 600519)')
    parser.add_argument('--output', '-o', help='输出文件路径')
    parser.add_argument('--max-discussions', type=int, default=10, help='最大讨论数 (默认 10)')
    parser.add_argument('--max-news', type=int, default=10, help='最大资讯数 (默认 10)')
    parser.add_argument('--api-key', help='GLM-5 API Key (也可通过 BAILIAN_API_KEY 环境变量设置)')
    parser.add_argument('--no-headless', action='store_true', help='显示浏览器界面')
    
    args = parser.parse_args()
    
    # 获取 API Key
    api_key = args.api_key or os.environ.get('BAILIAN_API_KEY', '')
    if not api_key:
        print("⚠️  警告: 未配置 BAILIAN_API_KEY，报告生成可能失败")
        print("   请设置环境变量: export BAILIAN_API_KEY=your-key\n")
    
    # 创建分析器
    analyzer = XueqiuAnalyzer(
        api_key=api_key,
        headless=not args.no_headless
    )
    
    # 执行分析
    try:
        analyzer.analyze_and_save(
            symbol=args.symbol,
            output_path=args.output,
            max_discussions=args.max_discussions,
            max_news=args.max_news
        )
    except Exception as e:
        print(f"\n❌ 分析失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()