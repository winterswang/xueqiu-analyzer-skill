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
class Article:
    """专栏文章"""
    title: str
    author: str
    time: str
    content: str
    link: str
    article_id: str = ""


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
    link: str = ""  # 资讯链接


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
    articles: List[Article] = None  # 新增：专栏文章
    financial_data: dict = None  # 新增：财务数据
    
    def __post_init__(self):
        if self.discussions is None:
            self.discussions = []
        if self.news is None:
            self.news = []
        if self.notices is None:
            self.notices = []
        if self.articles is None:
            self.articles = []
        if self.financial_data is None:
            self.financial_data = {}


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
    
    def _crawl_article_detail(self, page: Page, url: str) -> Optional[Article]:
        """爬取文章详情"""
        try:
            page.goto(url, timeout=30000)
            page.wait_for_timeout(2000)
            
            # 获取标题
            title = page.title()
            if '雪球' in title:
                title = title.split('-')[0].strip()
            
            # 获取作者
            author_elem = page.query_selector('.article__bd__from a, .user-name, .author-name')
            author = author_elem.inner_text().strip() if author_elem else ''
            
            # 获取时间
            time_elem = page.query_selector('.article__bd__from .date, .time, .date')
            time_str = time_elem.inner_text().strip() if time_elem else ''
            
            # 获取正文内容
            content_elem = page.query_selector('.article__bd__detail')
            if content_elem:
                content = content_elem.inner_text().strip()
            else:
                # 备选选择器
                content_elem = page.query_selector('.status-content, article')
                content = content_elem.inner_text().strip() if content_elem else ''
            
            # 提取文章ID
            article_id = ''
            match = re.search(r'/(\d+)$', url)
            if match:
                article_id = match.group(1)
            
            return Article(
                title=title[:100],
                author=author,
                time=time_str,
                content=content[:5000],  # 限制长度
                link=url,
                article_id=article_id
            )
            
        except Exception as e:
            self.logger.warning(f"爬取文章详情失败 {url}: {e}")
            return None
    
    def _extract_symbol(self, symbol: str) -> str:
        """提取股票代码"""
        # 去掉可能的前缀
        symbol = symbol.upper()
        symbol = re.sub(r'^[A-Z]{1,2}', '', symbol)  # 去掉市场前缀如 SH, SZ, US
        return symbol
    
    def crawl(self, symbol: str, max_discussions: int = 10, max_news: int = 10, max_articles: int = 5) -> StockInfo:
        """
        爬取股票详情页数据
        
        Args:
            symbol: 股票代码 (如 APP, TCOM, 600519)
            max_discussions: 最大讨论数
            max_news: 最大资讯数
            max_articles: 最大文章数
            
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
                
                # 3. 获取财务数据（新增）
                self.logger.info("获取财务数据...")
                try:
                    from financial_fetcher import FinancialDataFetcher
                    fetcher = FinancialDataFetcher()
                    # 传递 cookies 给雪球 API
                    cookies = context.cookies()
                    financial_data = fetcher.fetch(symbol, cookies)
                    if financial_data:
                        stock_info.financial_data = fetcher.to_dict(financial_data)
                        self.logger.info(f"  财务数据: PE={financial_data.pe_ttm:.1f}, ROE={financial_data.roe:.1f}%")
                except Exception as e:
                    self.logger.warning(f"财务数据获取失败: {e}")
                
                # 3. 访问讨论页
                self.logger.info(f"访问讨论页: /S/{symbol}/column")
                page.goto(f'https://xueqiu.com/S/{symbol}/column', timeout=30000)
                self._random_delay(3, 5)
                
                # 等待内容加载
                try:
                    page.wait_for_selector('.timeline__item', timeout=10000)
                except:
                    self.logger.warning("等待讨论内容超时")
                
                # ========== 滚动加载更多文章 ==========
                self.logger.info("滚动加载更多文章...")
                article_links = []  # 收集文章链接
                seen_links = set()  # 去重
                scroll_count = 0
                max_scrolls = 20  # 最多滚动20次
                min_content_length = 100  # 最小内容长度（降低阈值）
                max_articles = 20  # 最多收集20篇文章
                
                # 当前日期（用于判断是否在一周内）
                from datetime import datetime, timedelta
                one_week_ago = datetime.now() - timedelta(days=7)
                
                while scroll_count < max_scrolls and len(article_links) < max_articles:
                    # 获取当前所有讨论项
                    items = page.query_selector_all('.timeline__item')
                    
                    for item in items:
                        try:
                            text = item.inner_text().strip()
                            content_length = len(text)
                            
                            # 获取所有链接，找到文章链接
                            all_links = item.query_selector_all('a')
                            article_href = None
                            
                            for link_elem in all_links:
                                href = link_elem.get_attribute('href') or ''
                                # 检查是否是文章链接格式：/用户ID/文章ID
                                if re.match(r'/\d+/\d+$', href):
                                    article_href = href
                                    break
                            
                            if article_href:
                                full_url = 'https://xueqiu.com' + article_href
                                
                                # 检查是否已收集
                                if full_url not in seen_links:
                                    # 检查内容长度
                                    if content_length >= min_content_length:
                                        seen_links.add(full_url)
                                        article_links.append({
                                            'url': full_url,
                                            'content_preview': text[:200]
                                        })
                                        self.logger.info(f"  收集文章 [{len(article_links)}]: {text[:50]}...")
                        except Exception as e:
                            self.logger.debug(f"解析讨论项失败: {e}")
                    
                    # 检查是否已经足够
                    if len(article_links) >= max_articles:
                        break
                    
                    # 滚动到底部
                    page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                    self._random_delay(2, 3)
                    scroll_count += 1
                    self.logger.info(f"滚动 [{scroll_count}/{max_scrolls}]，已收集 {len(article_links)} 篇文章")
                
                self.logger.info(f"共收集 {len(article_links)} 篇文章链接")
                
                # 解析讨论（用于报告）
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
                        
                        # 获取链接（用于讨论显示）
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
                
                # 4. 爬取文章详情
                if article_links:
                    self.logger.info(f"开始爬取 {min(len(article_links), max_articles)} 篇文章详情...")
                    for i, article_info in enumerate(article_links[:max_articles]):
                        try:
                            self._random_delay(2, 4)
                            article_url = article_info['url'] if isinstance(article_info, dict) else article_info
                            article = self._crawl_article_detail(page, article_url)
                            if article and article.content:
                                stock_info.articles.append(article)
                                self.logger.info(f"  文章 [{i+1}]: {article.title[:30]}...")
                        except Exception as e:
                            self.logger.warning(f"  爬取文章失败: {e}")
                
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
                        
                        # 获取资讯链接
                        news_link = ''
                        link_elems = item.query_selector_all('a')
                        for link_elem in link_elems:
                            href = link_elem.get_attribute('href') or ''
                            # 资讯链接格式：/S/{symbol}/{id} 或外部链接
                            if re.match(r'/S/\w+/\d+$', href) or href.startswith('http'):
                                news_link = href if href.startswith('http') else 'https://xueqiu.com' + href
                                break
                        
                        if title and len(title) > 5:
                            stock_info.news.append(News(
                                title=title[:100],
                                time=time_str,
                                source='雪球',
                                link=news_link
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
            'articles': [asdict(a) for a in stock_info.articles],
            'news': [asdict(n) for n in stock_info.news],
            'notices': [asdict(n) for n in stock_info.notices],
            'financial_data': stock_info.financial_data,  # 新增
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