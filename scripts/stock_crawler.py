#!/usr/bin/env python3
"""
雪球股票详情页爬虫

功能：
- 爬取股票基本信息
- 爬取讨论/评论
- 爬取资讯新闻
- 爬取公告链接
"""

import os
import sys
import json
import re
import time
import random
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict

try:
    from playwright.sync_api import sync_playwright, Page, BrowserContext
except ImportError:
    print("请先安装 playwright: pip install playwright && playwright install chromium")
    sys.exit(1)


@dataclass
class Discussion:
    """讨论数据"""
    author: str
    time: str
    content: str
    link: str = ""


@dataclass
class News:
    """资讯数据"""
    title: str
    time: str
    source: str = ""


@dataclass
class Notice:
    """公告数据"""
    title: str
    link: str
    id: str = ""


@dataclass
class StockInfo:
    """股票信息"""
    symbol: str
    name: str = ""
    price: str = ""
    change: str = ""
    discussions: List[Discussion] = None
    news: List[News] = None
    notices: List[Notice] = None
    
    def __post_init__(self):
        if self.discussions is None:
            self.discussions = []
        if self.news is None:
            self.news = []
        if self.notices is None:
            self.notices = []


class XueqiuStockCrawler:
    """雪球股票详情页爬虫"""
    
    def __init__(self, headless: bool = True):
        self.headless = headless
        self.logger = self._setup_logger()
        
    def _setup_logger(self) -> logging.Logger:
        """配置日志"""
        logger = logging.getLogger('XueqiuStockCrawler')
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        return logger
    
    def _create_browser_context(self, playwright) -> tuple:
        """创建反检测浏览器上下文"""
        browser = playwright.chromium.launch(
            headless=self.headless,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--no-sandbox',
                '--disable-dev-shm-usage',
            ]
        )
        
        context = browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            locale='zh-CN',
        )
        
        # 绕过 webdriver 检测
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });
            window.chrome = { runtime: {} };
        """)
        
        return browser, context
    
    def _random_delay(self, min_sec: float = 2, max_sec: float = 5):
        """随机延迟"""
        delay = random.uniform(min_sec, max_sec)
        time.sleep(delay)
    
    def _extract_symbol(self, symbol: str) -> str:
        """提取股票代码"""
        # 去掉可能的前缀
        symbol = symbol.upper()
        symbol = re.sub(r'^[A-Z]{1,2}', '', symbol)  # 去掉市场前缀如 SH, SZ, US
        return symbol
    
    def crawl(self, symbol: str, max_discussions: int = 10, max_news: int = 10) -> StockInfo:
        """
        爬取股票详情页数据
        
        Args:
            symbol: 股票代码 (如 APP, TCOM, 600519)
            max_discussions: 最大讨论数
            max_news: 最大资讯数
            
        Returns:
            StockInfo: 股票信息
        """
        self.logger.info(f"开始爬取股票: {symbol}")
        
        stock_info = StockInfo(symbol=symbol)
        
        with sync_playwright() as p:
            browser, context = self._create_browser_context(p)
            page = context.new_page()
            
            try:
                # 1. 访问首页建立 cookies
                self.logger.info("访问雪球首页...")
                page.goto('https://xueqiu.com', timeout=30000)
                self._random_delay(2, 3)
                
                # 2. 访问股票详情页获取基本信息
                self.logger.info(f"访问股票详情页: /S/{symbol}")
                page.goto(f'https://xueqiu.com/S/{symbol}', timeout=30000)
                self._random_delay(3, 5)
                
                # 获取股票名称
                name_elem = page.query_selector('.stock-name')
                if name_elem:
                    stock_info.name = name_elem.inner_text().strip()
                    self.logger.info(f"股票名称: {stock_info.name}")
                
                # 获取价格信息
                price_elem = page.query_selector('.stock-current')
                if price_elem:
                    stock_info.price = price_elem.inner_text().strip()[:50]
                    self.logger.info(f"价格信息: {stock_info.price}")
                
                # 3. 访问讨论页
                self.logger.info(f"访问讨论页: /S/{symbol}/column")
                page.goto(f'https://xueqiu.com/S/{symbol}/column', timeout=30000)
                self._random_delay(3, 5)
                
                # 等待内容加载
                try:
                    page.wait_for_selector('.timeline__item', timeout=10000)
                except:
                    self.logger.warning("等待讨论内容超时")
                
                # 解析讨论
                items = page.query_selector_all('.timeline__item')
                self.logger.info(f"找到 {len(items)} 条讨论")
                
                for item in items[:max_discussions]:
                    try:
                        text = item.inner_text().strip()
                        
                        # 提取作者
                        author_match = re.search(r'^([^\d]+?)(?=\d+小时|\d+天|昨天|今天|\d{4})', text)
                        author = author_match.group(1).strip() if author_match else ''
                        
                        # 提取时间
                        time_match = re.search(r'(\d+小时前|\d+天前|昨天|今天|\d{2}:\d{2})', text)
                        time_str = time_match.group(1) if time_match else ''
                        
                        # 提取内容 - 清理
                        content = text
                        content = re.sub(r'^[^\d]+?\d+小时前[^\n]*', '', content)
                        content = re.sub(r'^[^\d]+?昨天[^\n]*', '', content)
                        content = re.sub(r'展开.*$', '', content)
                        content = re.sub(r'转发.*$', '', content)
                        content = content.strip()[:500]
                        
                        # 获取链接
                        link_elem = item.query_selector('a[href*="/{}/"]'.format(symbol))
                        href = ''
                        if link_elem:
                            h = link_elem.get_attribute('href') or ''
                            if re.match(r'/\d+/\d+', h):
                                href = 'https://xueqiu.com' + h
                        
                        if content and len(content) > 10:
                            stock_info.discussions.append(Discussion(
                                author=author,
                                time=time_str,
                                content=content,
                                link=href
                            ))
                    except Exception as e:
                        self.logger.warning(f"解析讨论失败: {e}")
                
                # 4. 访问资讯页
                self.logger.info(f"访问资讯页: /S/{symbol}/news")
                page.goto(f'https://xueqiu.com/S/{symbol}/news', timeout=30000)
                self._random_delay(3, 5)
                
                items = page.query_selector_all('.timeline__item')
                self.logger.info(f"找到 {len(items)} 条资讯")
                
                for item in items[:max_news]:
                    try:
                        text = item.inner_text().strip()
                        
                        # 提取标题
                        lines = text.split('\n')
                        title = lines[0] if lines else text[:100]
                        
                        # 提取时间
                        time_match = re.search(r'(\d+小时前|\d+天前|昨天|\d{2}-\d{2})', text)
                        time_str = time_match.group(1) if time_match else ''
                        
                        if title and len(title) > 5:
                            stock_info.news.append(News(
                                title=title[:100],
                                time=time_str,
                                source='雪球'
                            ))
                    except Exception as e:
                        self.logger.warning(f"解析资讯失败: {e}")
                
                # 5. 获取公告链接
                self.logger.info("获取公告链接...")
                page.goto(f'https://xueqiu.com/S/{symbol}', timeout=30000)
                self._random_delay(2, 3)
                
                page_content = page.content()
                notice_matches = re.findall(rf'/S/{symbol}/(\d+)', page_content)
                notice_matches = list(set(notice_matches))[:5]
                
                for nid in notice_matches:
                    stock_info.notices.append(Notice(
                        title='公告',
                        link=f'https://xueqiu.com/S/{symbol}/{nid}',
                        id=nid
                    ))
                
            except Exception as e:
                self.logger.error(f"爬取失败: {e}")
                import traceback
                traceback.print_exc()
                
            finally:
                browser.close()
        
        self.logger.info(f"爬取完成: {len(stock_info.discussions)} 讨论, {len(stock_info.news)} 资讯, {len(stock_info.notices)} 公告")
        return stock_info
    
    def to_dict(self, stock_info: StockInfo) -> dict:
        """转换为字典"""
        return {
            'symbol': stock_info.symbol,
            'name': stock_info.name,
            'price': stock_info.price,
            'discussions': [asdict(d) for d in stock_info.discussions],
            'news': [asdict(n) for n in stock_info.news],
            'notices': [asdict(n) for n in stock_info.notices],
            'crawl_time': datetime.now().isoformat()
        }


def main():
    """测试"""
    import argparse
    
    parser = argparse.ArgumentParser(description='雪球股票详情页爬虫')
    parser.add_argument('symbol', help='股票代码')
    parser.add_argument('--max-discussions', type=int, default=10, help='最大讨论数')
    parser.add_argument('--max-news', type=int, default=10, help='最大资讯数')
    parser.add_argument('--output', '-o', help='输出文件路径')
    
    args = parser.parse_args()
    
    crawler = XueqiuStockCrawler(headless=True)
    result = crawler.crawl(
        symbol=args.symbol,
        max_discussions=args.max_discussions,
        max_news=args.max_news
    )
    
    data = crawler.to_dict(result)
    
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"结果已保存到: {args.output}")
    else:
        print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()