#!/usr/bin/env python3
"""
迭代式爬取策略

目标：通过多轮迭代，获取高质量、全面的内容

策略：
1. 第一轮：快速爬取，评估内容质量
2. 第二轮：根据缺失主题，定向补充
3. 第三轮：深度爬取，获取长文

评估指标：
- 文章数量 >= 10 篇
- 长文章比例 >= 50% (>=1000字符)
- 主题覆盖度 >= 80%
"""

import os
import sys
import json
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from stock_crawler_v2 import XueqiuStockCrawlerV2


class IterativeCrawler:
    """迭代式爬取器"""
    
    # 需要覆盖的主题
    REQUIRED_TOPICS = [
        '估值', '护城河', '竞争', '管理层', 
        '现金流', 'AI', '反垄断', '用户'
    ]
    
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.all_articles = []
        self.all_discussions = []
        self.seen_links = set()
        
    def assess_quality(self) -> dict:
        """评估当前数据质量"""
        # 文章数量
        article_count = len(self.all_articles)
        
        # 长文章比例
        long_articles = [a for a in self.all_articles if len(a.get('content', '')) >= 1000]
        long_ratio = len(long_articles) / article_count if article_count > 0 else 0
        
        # 主题覆盖
        covered_topics = set()
        for a in self.all_articles:
            content = a.get('content', '')
            for topic in self.REQUIRED_TOPICS:
                if topic in content:
                    covered_topics.add(topic)
        
        topic_coverage = len(covered_topics) / len(self.REQUIRED_TOPICS)
        
        return {
            'article_count': article_count,
            'discussion_count': len(self.all_discussions),
            'long_article_count': len(long_articles),
            'long_article_ratio': long_ratio,
            'covered_topics': list(covered_topics),
            'missing_topics': [t for t in self.REQUIRED_TOPICS if t not in covered_topics],
            'topic_coverage': topic_coverage,
            'quality_score': self._calculate_quality_score(
                article_count, long_ratio, topic_coverage
            )
        }
    
    def _calculate_quality_score(self, count, long_ratio, coverage) -> float:
        """计算质量分数 (0-100)"""
        # 数量分数 (目标: 10+)
        count_score = min(count / 10, 1.0) * 30
        
        # 长文章分数 (目标: 50%+)
        length_score = min(long_ratio / 0.5, 1.0) * 30
        
        # 主题覆盖分数 (目标: 80%+)
        coverage_score = min(coverage / 0.8, 1.0) * 40
        
        return count_score + length_score + coverage_score
    
    def crawl_round(self, max_pages: int = 3, max_articles: int = 10) -> dict:
        """执行一轮爬取"""
        crawler = XueqiuStockCrawlerV2(headless=True)
        
        result = crawler.crawl(
            symbol=self.symbol,
            max_discussions=30,
            max_news=20,
            max_articles=max_articles,
            max_scrolls=max_pages
        )
        
        data = crawler.to_dict(result)
        
        # 合并数据（去重）
        new_articles = 0
        for a in data.get('articles', []):
            link = a.get('link', '')
            if link and link not in self.seen_links:
                self.seen_links.add(link)
                self.all_articles.append(a)
                new_articles += 1
        
        new_discussions = 0
        for d in data.get('discussions', []):
            link = d.get('link', '')
            if link and link not in self.seen_links:
                self.seen_links.add(link)
                self.all_discussions.append(d)
                new_discussions += 1
        
        return {
            'new_articles': new_articles,
            'new_discussions': new_discussions,
            'total_articles': len(self.all_articles),
            'total_discussions': len(self.all_discussions)
        }
    
    def run(self, max_rounds: int = 3, target_score: float = 70) -> dict:
        """执行迭代爬取"""
        print(f"\n{'='*60}")
        print(f"迭代式爬取: {self.symbol}")
        print(f"目标质量分: {target_score}")
        print(f"{'='*60}\n")
        
        results = []
        
        for round_num in range(1, max_rounds + 1):
            print(f"\n--- 第 {round_num} 轮爬取 ---")
            
            # 根据轮次调整策略
            if round_num == 1:
                pages, articles = 3, 10
            elif round_num == 2:
                pages, articles = 5, 15
            else:
                pages, articles = 7, 20
            
            # 执行爬取
            crawl_result = self.crawl_round(max_pages=pages, max_articles=articles)
            print(f"新增: {crawl_result['new_articles']} 文章, {crawl_result['new_discussions']} 讨论")
            
            # 评估质量
            quality = self.assess_quality()
            print(f"质量分: {quality['quality_score']:.1f}/100")
            print(f"文章: {quality['article_count']}, 长文: {quality['long_article_count']}")
            print(f"主题覆盖: {quality['topic_coverage']*100:.0f}%")
            print(f"缺失主题: {quality['missing_topics']}")
            
            results.append({
                'round': round_num,
                'crawl': crawl_result,
                'quality': quality
            })
            
            # 检查是否达到目标
            if quality['quality_score'] >= target_score:
                print(f"\n✅ 达到目标质量分!")
                break
            
            # 检查是否无法继续提升
            if crawl_result['new_articles'] == 0:
                print(f"\n⚠️ 无新内容，停止迭代")
                break
            
            # 间隔
            time.sleep(2)
        
        return {
            'rounds': results,
            'final_quality': self.assess_quality(),
            'articles': self.all_articles,
            'discussions': self.all_discussions
        }


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='迭代式爬取')
    parser.add_argument('symbol', help='股票代码')
    parser.add_argument('--max-rounds', type=int, default=3, help='最大轮次')
    parser.add_argument('--target-score', type=float, default=70, help='目标质量分')
    
    args = parser.parse_args()
    
    crawler = IterativeCrawler(args.symbol)
    result = crawler.run(max_rounds=args.max_rounds, target_score=args.target_score)
    
    # 保存结果
    output = {
        'symbol': args.symbol,
        'final_quality': result['final_quality'],
        'articles': result['articles'],
        'discussions': result['discussions']
    }
    
    output_path = f'data/reports/{args.symbol}_iterative_crawl.json'
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f"\n结果已保存: {output_path}")


if __name__ == '__main__':
    main()