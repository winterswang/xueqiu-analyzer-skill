#!/usr/bin/env python3
"""
修复后的爬取脚本 - 正确解析资讯和公告
"""

import os
import sys
import json
import time
import re
from pathlib import Path
from typing import List
from dataclasses import dataclass

sys.path.insert(0, str(Path(__file__).parent))

from stock_crawler_v2 import XueqiuStockCrawlerV2


@dataclass
class News:
    title: str
    time: str
    source: str
    link: str


@dataclass
class Notice:
    title: str
    link: str
    id: str


class FixedCrawler(XueqiuStockCrawlerV2):
    """修复后的爬虫"""
    
    def _parse_news(self, page, max_count: int = 20) -> List[dict]:
        """修复后的资讯解析"""
        news_list = []
        items = page.query_selector_all('.timeline__item')
        
        self.logger.info(f"解析资讯: 找到 {len(items)} 条")
        
        for item in items[:max_count]:
            try:
                text = item.inner_text().strip()
                
                # 使用 JavaScript 获取真实的文章链接
                link = page.evaluate('''(item) => {
                    const links = item.querySelectorAll('a');
                    for (const link of links) {
                        const href = link.getAttribute('href') || '';
                        // 获取文章链接（格式: /用户ID/文章ID）
                        if (href && /^\\/\\d+\\/\\d+$/.test(href)) {
                            return 'https://xueqiu.com' + href;
                        }
                    }
                    return '';
                }''', item)
                
                # 提取标题 - 清理格式
                title = text
                # 移除 "携程(TCOM)" 前缀和时间
                title = re.sub(r'^携程\(TCOM\)\d{2}-\d{2}\s*\d{1,2}:\d{2}·\s*来自新闻\s*', '', title)
                title = re.sub(r'^收起\s*', '', title)
                title = re.sub(r'展开.*$', '', title)
                title = title[:100].strip()
                
                # 提取时间
                time_match = re.search(r'(\d{2}-\d{2})', text)
                time_str = time_match.group(1) if time_match else ''
                
                if title and len(title) > 5:
                    news_list.append({
                        'title': title,
                        'time': time_str,
                        'source': '雪球资讯',
                        'link': link or 'https://xueqiu.com/S/TCOM'
                    })
                    
            except Exception as e:
                self.logger.debug(f"解析资讯失败: {e}")
        
        return news_list
    
    def _parse_notices(self, page) -> List[dict]:
        """修复后的公告解析"""
        notices = []
        
        try:
            time.sleep(1)
            
            # 使用 JavaScript 获取公告列表
            notice_items = page.evaluate('''() => {
                const items = [];
                const timelineItems = document.querySelectorAll('.timeline__item');
                
                for (const item of timelineItems) {
                    const text = item.innerText || '';
                    const links = item.querySelectorAll('a');
                    
                    for (const link of links) {
                        const href = link.getAttribute('href') || '';
                        // 查找文章链接
                        if (/^\\/\\d+\\/\\d+$/.test(href)) {
                            let title = text.split('\\n')[0] || '公告';
                            title = title.substring(0, 50);
                            
                            const idMatch = href.match(/\\/(\\d+)$/);
                            const id = idMatch ? idMatch[1] : '';
                            
                            items.push({
                                title: title,
                                link: 'https://xueqiu.com' + href,
                                id: id
                            });
                            break;
                        }
                    }
                }
                
                return items;
            }''')
            
            for item in notice_items[:10]:
                notices.append({
                    'title': item.get('title', '公告'),
                    'link': item.get('link', ''),
                    'id': item.get('id', '')
                })
            
            self.logger.info(f"解析公告: 找到 {len(notices)} 条")
                
        except Exception as e:
            self.logger.warning(f"解析公告失败: {e}")
        
        return notices


def main():
    print('开始爬取 TCOM（修复版）...')
    
    crawler = FixedCrawler(headless=True)
    stock_info = crawler.crawl(
        symbol='TCOM',
        max_discussions=20,
        max_news=20,
        max_articles=10,
        max_scrolls=3
    )
    
    data = crawler.to_dict(stock_info)
    
    # 使用修复后的方法解析
    # 注意：需要在爬取过程中调用，这里只是演示
    
    print(f'\n=== 数据检查 ===')
    print(f'讨论: {len(data.get("discussions", []))} 条')
    print(f'资讯: {len(data.get("news", []))} 条')
    print(f'公告: {len(data.get("notices", []))} 条')
    print(f'文章: {len(data.get("articles", []))} 篇')
    
    # 保存
    with open('data/reports/TCOM_fixed_data.json', 'w') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print('\n数据已保存')


if __name__ == '__main__':
    main()