"""
xueqiu-analyzer V3 — 雪球数据爬虫

从 V2 stock_crawler_v2.py 迁移，核心改动：
1. 去掉内部 dataclass，使用 V3 models
2. crawl() 返回 CrawlResult
3. 增加独立的 save/load 方法
4. 保留所有浏览器操作和反检测逻辑
"""

import os
import json
import re
import time
import random
import logging
import requests
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

try:
    from playwright.sync_api import sync_playwright, Page, BrowserContext
except ImportError:
    raise ImportError("请安装 playwright: pip install playwright && playwright install chromium")

try:
    import fitz  # PyMuPDF for PDF text extraction
except ImportError:
    fitz = None

from .models import (
    CrawlResult, Discussion, News, Notice, Article,
)
from .extractor import ScrapingExtractor

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_DIR = os.path.expanduser('~/.xueqiu_crawler')


def _xueqiu_url_for_symbol(symbol: str) -> str:
    """将股票代码转换为雪球股票详情页 URL

    A 股：6位数字 → 添加 SH/SZ 前缀
    港股：5位数字（00700）→ 直接使用
    美股：字母代码（PDD/AAPL）→ 直接使用
    """
    symbol = symbol.strip()
    # A 股：6位数字
    if symbol.isdigit() and len(symbol) == 6:
        if symbol.startswith('6') or symbol.startswith('5'):
            return f'https://xueqiu.com/S/SH{symbol}'
        else:  # 0, 1, 2, 3, 8 开头 → 深圳
            return f'https://xueqiu.com/S/SZ{symbol}'
    # 其他（港股如 00700，美股如 PDD）直接使用
    return f'https://xueqiu.com/S/{symbol}'


# ── 免责声明/无用内容关键词集合 ──
_DISCLAIMER_PHRASES = frozenset([
    "竭力确保所提供信息的准确和可靠",
    "不能保证其绝对准确和可靠",
    "不会承担因任何不准确或遗漏而引起的任何损失或损害",
    "力求但不保证所有信息完全准确",
    "不构成任何投资建议",
    "所述内容仅供参考",
    "本页面内容仅供参考",
])


def _is_disclaimer(text: str) -> bool:
    """检查文本是否为免责声明/无用内容"""
    if not text:
        return True
    for phrase in _DISCLAIMER_PHRASES:
        if phrase in text:
            return True
    return False


class XueqiuCrawler:
    """雪球数据爬虫 — 只管爬，输出标准 CrawlResult"""

    def __init__(self, config: dict = None):
        self.headless = (config or {}).get('headless', True)
        self.delay_min = (config or {}).get('delay_min', 3)
        self.delay_max = (config or {}).get('delay_max', 8)
        self.timeout = (config or {}).get('timeout', 30000)
        self.config_dir = DEFAULT_CONFIG_DIR
        os.makedirs(self.config_dir, exist_ok=True)
        self.cookies_path = os.path.join(self.config_dir, 'cookies.json')
        self.credentials_path = os.path.join(self.config_dir, 'credentials.yaml')
        self.credentials = self._load_credentials()
        self.logger = logger
        self.extractor = ScrapingExtractor()

    def crawl(self, symbol: str, max_pages: int = 5,
              max_articles: int = 10,
              days: int = 0,
              max_news: int = 20,
              max_notices: int = 20) -> CrawlResult:
        """
        爬取股票详情页数据

        Args:
            symbol: 股票代码
            max_pages: 最大分页数
            max_articles: 最大文章数
            days: 时间过滤（0=不限，N=只看最近 N 天）
            max_news: 最大爬取新闻正文数（0=只爬标题）
            max_notices: 最大爬取公告正文数（PDF解析）

        Returns:
            CrawlResult
        """
        self.logger.info(f"开始爬取股票: {symbol}")
        result = CrawlResult(symbol=symbol)

        with sync_playwright() as p:
            browser, context = self._create_browser_context(p)
            page = context.new_page()

            try:
                # 1. 访问首页检查登录
                self.logger.info("访问雪球首页...")
                page.goto('https://xueqiu.com', timeout=self.timeout)
                self.human_delay(2, 4)

                if not self._check_login_status(page):
                    self.logger.info("未登录，尝试登录...")
                    self._login(page)
                    time.sleep(2)

                self._close_modal(page)

                # 2. 访问股票详情页
                url = _xueqiu_url_for_symbol(symbol)
                self.logger.info(f"访问股票详情页: {url}")
                page.goto(url, timeout=max(self.timeout, 60000))
                self.human_delay(3, 6)

                self._close_modal(page)

                # 获取股票名称
                name_elem = page.query_selector('.stock-name')
                if name_elem:
                    result.name = name_elem.inner_text().strip()
                    self.logger.info(f"股票名称: {result.name}")

                # 当前价格：多选择器兼容
                price_selectors = [
                    '.stock-current',
                    '.stock-current-price',
                    '[class*="stock-current"]',
                    '[class*="current-price"]',
                    '[data-test="current-price"]',
                ]
                for sel in price_selectors:
                    price_elem = page.query_selector(sel)
                    if price_elem:
                        result.price = price_elem.inner_text().strip()[:50]
                        self.logger.info(f"股价: {result.price}")
                        break

                # 涨跌幅
                change_selectors = [
                    '.stock-change',
                    '.stock-percent',
                    '[class*="stock-change"]',
                    '[class*="price-change"]',
                ]
                for sel in change_selectors:
                    change_elem = page.query_selector(sel)
                    if change_elem:
                        result.change = change_elem.inner_text().strip()[:50]
                        break

                # ========== 爬取讨论 ==========
                self.logger.info("=== 爬取讨论 (API) ===")
                api_discs = self._crawl_discussions_via_api(
                    symbol, max_pages=max_pages, per_page=50, days=days)
                for disc in api_discs:
                    if disc.is_column and disc.link:
                        result.articles.append(Article(
                            title=disc.content[:80],
                            author=disc.author,
                            content=disc.content,
                            time=disc.time,
                            link=disc.link,
                            is_column=True,
                        ))
                    else:
                        result.discussions.append(disc)
                self.logger.info(f"获取 {len(result.discussions)} 条讨论（含 {sum(1 for d in result.discussions if d.is_column)} 专栏）")

                # ========== 爬取资讯 ==========
                self.logger.info("=== 爬取资讯 (API) ===")
                result.news = self._crawl_news_via_api(symbol, max_count=30, days=days)
                self.logger.info(f"获取 {len(result.news)} 条资讯")

                # ========== 爬取资讯详情（正文） ==========
                if max_news > 0:
                    self.logger.info(f"爬取 {min(max_news, len(result.news))} 条资讯详情...")
                    for i, n in enumerate(result.news[:max_news]):
                        detail = self._crawl_news_detail(browser, n.link)
                        if detail:
                            n.content = detail.get('content', '') or n.content
                            if detail.get('title'):
                                n.title = detail['title']
                        if i < len(result.news) - 1:
                            self.human_delay(1.5, 3.0)
                    self.logger.info(f"资讯详情爬取完成")

                # ========== 爬取公告 ==========
                self.logger.info("=== 爬取公告 (API) ===")
                result.notices = self._crawl_notices_via_api(symbol, max_pages=max_pages, days=days)
                self.logger.info(f"获取 {len(result.notices)} 条公告")

                # ========== 爬取公告正文（PDF） ==========
                if max_notices > 0:
                    self.logger.info(f"爬取 {min(max_notices, len(result.notices))} 条公告正文...")
                    success_count = 0
                    fail_count = 0
                    for i, nt in enumerate(result.notices[:max_notices]):
                        if nt.link and (nt.link.endswith('.pdf') or 'stockmc.xueqiu.com' in nt.link):
                            text = self._crawl_notice_pdf_text(nt.link)
                            if text and len(text) > 50:
                                nt.content = text
                                success_count += 1
                                self.logger.info(f"  ✅ [{i+1}/{min(max_notices, len(result.notices))}] {len(text)}字: {nt.title[:40]}")
                            else:
                                fail_count += 1
                                self.logger.warning(f"  ❌ [{i+1}/{min(max_notices, len(result.notices))}] 提取失败: {nt.title[:40]}")
                        else:
                            self.logger.debug(f"  ⊘ 非PDF跳过: {nt.link}")
                        if i < len(result.notices) - 1:
                            self.human_delay(1.0, 2.0)
                    self.logger.info(f"公告正文爬取完成: {success_count}成功/{fail_count}失败")

                # ========== 爬取文章 ==========
                self.logger.info(f"\n爬取 {max_articles} 篇文章详情...")
                # 从讨论和资讯中提取文章链接
                article_links = []
                for disc in result.discussions:
                    if disc.link and re.match(r'https://xueqiu\.com/\d+/\d+', disc.link):
                        article_links.append(disc.link)
                if len(article_links) < max_articles:
                    for n in result.news:
                        if n.link and re.match(r'https://xueqiu\.com/\d+/\d+', n.link):
                            article_links.append(n.link)

                seen = set()
                for link in article_links[:max_articles]:
                    if link in seen:
                        continue
                    seen.add(link)
                    try:
                        article = self._crawl_article_detail(page, link)
                        if article:
                            result.articles.append(article)
                    except Exception:
                        pass

                # 保存 cookies
                self._save_cookies(context)

            finally:
                browser.close()

        self.logger.info(f"爬取完成: {len(result.discussions)} 讨论, "
                         f"{len(result.news)} 资讯, "
                         f"{len(result.notices)} 公告, "
                         f"{len(result.articles)} 文章")
        return result

    # ========== 辅助方法（从 V2 迁移，逻辑不变）==========

    def human_delay(self, min_s: float = None, max_s: float = None):
        """模拟人类操作的随机延迟"""
        lo = min_s or self.delay_min
        hi = max_s or self.delay_max
        delay = random.uniform(lo, hi)
        self.logger.debug(f"  ⏳ 延迟 {delay:.1f}s")
        time.sleep(delay)

    def _load_credentials(self) -> dict:
        if os.path.exists(self.credentials_path):
            try:
                import yaml
                with open(self.credentials_path, 'r') as f:
                    return yaml.safe_load(f) or {}
            except Exception:
                pass
        return {}

    def _create_browser_context(self, playwright) -> Tuple:
        launch_opts = dict(
            headless=self.headless,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--no-sandbox',
                '--disable-dev-shm-usage',
                '--disable-infobars',
                '--window-size=1920,1080',
            ]
        )
        sys_chromium = '/usr/bin/chromium-browser'
        if os.path.exists(sys_chromium):
            launch_opts['executable_path'] = sys_chromium

        browser = playwright.chromium.launch(**launch_opts)

        context = browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36',
            locale='zh-CN',
            timezone_id='Asia/Shanghai',
            geolocation={'latitude': 31.2304, 'longitude': 121.4737},
            permissions=['geolocation'],
            color_scheme='light',
            device_scale_factor=2,
            is_mobile=False,
            has_touch=False,
        )

        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en-US', 'en'] });
            Object.defineProperty(navigator, 'platform', { get: () => 'MacIntel' });
            Object.defineProperty(navigator, 'vendor', { get: () => 'Google Inc.' });
            Object.defineProperty(navigator, 'maxTouchPoints', { get: () => 0 });
            Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
            Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });
            window.chrome = { runtime: {}, loadTimes: function(){}, csi: function(){} };
            Object.defineProperty(navigator, 'plugins', {
                get: () => {
                    const p = [
                        { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer' },
                        { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai' },
                        { name: 'Native Client', filename: 'internal-nacl-plugin' },
                    ];
                    p.length = 3;
                    return p;
                }
            });
            const getParameter = WebGLRenderingContext.prototype.getParameter;
            WebGLRenderingContext.prototype.getParameter = function(parameter) {
                if (parameter === 37445) return 'Apple Inc.';
                if (parameter === 37446) return 'Apple GPU';
                return getParameter.call(this, parameter);
            };
        """)

        # 加载 cookies
        if os.path.exists(self.cookies_path):
            try:
                with open(self.cookies_path, 'r') as f:
                    cookies = json.load(f)
                    context.add_cookies(cookies)
                    self.logger.info(f"已加载 {len(cookies)} 个 cookies")
            except Exception as e:
                self.logger.warning(f"加载 cookies 失败: {e}")

        return browser, context

    def _save_cookies(self, context: BrowserContext):
        try:
            cookies = context.cookies()
            with open(self.cookies_path, 'w') as f:
                json.dump(cookies, f)
            # 双写到项目目录
            project_cookies = Path(__file__).parent.parent.parent / 'config' / 'cookies' / 'xueqiu.json'
            project_cookies.parent.mkdir(parents=True, exist_ok=True)
            with open(project_cookies, 'w') as f:
                json.dump(cookies, f)
            self.logger.info(f"已保存 {len(cookies)} 个 cookies")
        except Exception as e:
            self.logger.warning(f"保存 cookies 失败: {e}")

    def _check_login_status(self, page: Page) -> bool:
        try:
            content = page.content()
            if '访问验证' in content or '请按住滑块' in content:
                return False
            if 'snb-container' in content or page.query_selector('[class*="user-name"]'):
                return True
            return False
        except Exception:
            return False

    def _login(self, page: Page) -> bool:
        creds = self.credentials.get('xueqiu', {})
        phone = creds.get('phone', '')
        password = creds.get('password', '')
        if not phone or not password:
            self.logger.info("未配置登录凭据，跳过登录")
            return False
        # 登录逻辑保持与 V2 一致（简化版）
        self.logger.info(f"尝试登录: {phone[:3]}****")
        try:
            login_btn = page.query_selector('text=登录')
            if login_btn:
                login_btn.click()
                time.sleep(2)
            phone_tab = page.query_selector('text=手机号登录')
            if phone_tab:
                phone_tab.click()
                time.sleep(1)
            phone_input = page.query_selector('input[placeholder*="手机号"]')
            if phone_input:
                phone_input.fill(phone)
            pwd_input = page.query_selector('input[placeholder*="密码"]')
            if pwd_input:
                pwd_input.fill(password)
            time.sleep(1)
            submit = page.query_selector('button:has-text("登录")')
            if submit:
                submit.click()
                time.sleep(5)
            return self._check_login_status(page)
        except Exception as e:
            self.logger.error(f"登录失败: {e}")
            return False

    def _close_modal(self, page: Page) -> bool:
        try:
            modal = page.query_selector('.modals.dimmer.js-shown')
            if modal:
                self.logger.info("检测到登录弹窗，尝试关闭...")
                close_btn = page.query_selector('.modal__close, .close, [class*="close"]')
                if close_btn:
                    try:
                        close_btn.click(timeout=3000)
                        time.sleep(0.5)
                        return True
                    except Exception:
                        pass
                # JS 关闭
                page.evaluate('''() => {
                    document.querySelectorAll('.modals.dimmer').forEach(m => m.remove());
                    document.body.classList.remove('dimmer');
                    const overlay = document.querySelector('.overlay');
                    if (overlay) overlay.remove();
                }''')
                self.logger.info("JavaScript 移除弹窗成功")
                return True
            return False
        except Exception:
            return False

    def _js_click(self, page: Page, text: str) -> bool:
        try:
            # 用 json.dumps 安全编码，避免 text 含引号时 JS 注入
            safe_text = json.dumps(text)
            return page.evaluate(f'''() => {{
                const elements = document.querySelectorAll('span, a, div, li');
                const target = {safe_text};
                for (const el of elements) {{
                    if (el.innerText.trim() === target || el.innerText.trim().startsWith(target)) {{
                        el.click();
                        return true;
                    }}
                }}
                return false;
            }}''')
        except Exception:
            return False

    def _switch_tab(self, page: Page, tab_name: str) -> bool:
        self.logger.info(f"切换到 '{tab_name}' tab...")
        if self._js_click(page, tab_name):
            self.human_delay(2, 4)
            try:
                page.wait_for_selector('.timeline__item', timeout=5000)
                return True
            except Exception:
                return True
        return False

    def _crawl_discussions_via_api(self, symbol: str, max_pages: int = 10,
                                    per_page: int = 50,
                                    days: int = 0) -> List[Discussion]:
        """通过雪球官方 API 爬取讨论（支持真正的分页翻页）。

        API: GET https://xueqiu.com/query/v1/symbol/search/status.json
        params: symbol, count, page, type=11 (讨论), sort=time, source=all

        Args:
            symbol: 股票代码
            max_pages: 最大分页数
            per_page: 每页条数（API 固定返回 20 条）
            days: 时间过滤（0=不限，N=只看最近 N 天）
        """
        discussions = []
        time_cutoff = 0
        if days > 0:
            time_cutoff = datetime.now().timestamp() - days * 86400

        try:
            cookies_path = Path(self.cookies_path)
            if not cookies_path.exists():
                cookies_path = Path(__file__).parent.parent.parent / 'config' / 'cookies' / 'xueqiu.json'
            if cookies_path.exists():
                with open(cookies_path) as f:
                    cookies = json.load(f)
            else:
                self.logger.warning("未找到 cookies 文件，跳过 API 爬取")
                return []

            token = next((c['value'] for c in cookies if c['name'] == 'xq_a_token'), None)
            if not token:
                self.logger.warning("未找到 xq_a_token，跳过 API 爬取")
                return []

            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
                'Cookie': f'xq_a_token={token}',
                'Referer': f'https://xueqiu.com/S/{symbol}',
                'Accept': 'application/json, text/plain, */*'
            }

            should_stop = False
            for page_num in range(1, max_pages + 1):
                url = (f'https://xueqiu.com/query/v1/symbol/search/status.json'
                       f'?count={per_page}&comment=0&symbol={symbol}'
                       f'&hl=0&source=all&sort=time&page={page_num}&q=&type=11')
                resp = requests.get(url, headers=headers, timeout=15)
                if resp.status_code != 200:
                    break
                items = resp.json().get('list', [])
                if not items:
                    break

                for item in items:
                    user = item.get('user', {})
                    if not isinstance(user, dict):
                        continue
                    screen_name = user.get('screen_name', '')
                    raw_content = item.get('description', '') or ''
                    content = re.sub(r'<[^>]+>', '', raw_content).strip()
                    status_id = item.get('id', '')
                    user_id = user.get('id', '')
                    created = item.get('created_at', 0)
                    ts = datetime.fromtimestamp(created / 1000).strftime('%Y-%m-%d %H:%M') if created else ''
                    link = f'https://xueqiu.com/{user_id}/{status_id}'
                    is_col = str(item.get('type', '')) == '2'

                    # 时间过滤：遇到超出范围的帖子，停止爬取
                    if days > 0 and created > 0 and created / 1000 < time_cutoff:
                        self.logger.info(f"  [时间过滤] 第 {page_num} 页遇到 {days} 天前的帖子，停止")
                        should_stop = True
                        break

                    if content and len(content) > 5:
                        discussions.append(Discussion(
                            author=screen_name,
                            content=content[:500],
                            time=ts,
                            link=link,
                            is_column=is_col,
                        ))

                self.logger.info(f"  API 页 {page_num}: {len(items)} 条 "
                                 f"(累计 {len(discussions)} 条, 专栏 {sum(1 for d in discussions if d.is_column)})")

                if len(items) < 20:
                    break

                self.human_delay(1.0, 2.0)

        except Exception as e:
            self.logger.warning(f"API 爬取讨论失败: {e}")
        return discussions

    def _crawl_news_via_api(self, symbol: str, max_count: int = 30, days: int = 0) -> List[News]:
        """通过雪球官方 API 爬取资讯（新闻/文章）。

        API: GET https://xueqiu.com/statuses/interview/search.json
        params: symbol, count
        """
        news_list = []
        try:
            cookies_path = Path(self.cookies_path)
            if not cookies_path.exists():
                cookies_path = Path(__file__).parent.parent.parent / 'config' / 'cookies' / 'xueqiu.json'
            if cookies_path.exists():
                with open(cookies_path) as f:
                    cookies = json.load(f)
            else:
                self.logger.warning("未找到 cookies，跳过资讯爬取")
                return []
            token = next((c['value'] for c in cookies if c['name'] == 'xq_a_token'), None)
            if not token:
                self.logger.warning("未找到 xq_a_token，跳过资讯爬取")
                return []
            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
                'Cookie': f'xq_a_token={token}',
                'Referer': f'https://xueqiu.com/S/{symbol}',
                'Accept': 'application/json, text/plain, */*'
            }
            # 港股news API也用纯数字
            symbol_id_map = {'HK00700': '00700'}
            news_symbol = symbol_id_map.get(symbol, symbol)
            url = f'https://xueqiu.com/statuses/interview/search.json?symbol={news_symbol}&count={max_count}'
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code != 200:
                self.logger.warning(f"资讯 API 返回 {resp.status_code}")
                return []
            interviews = resp.json().get('interviews', [])
            # 按时间排序（最新优先）并应用 days 过滤
            interviews_sorted = sorted(interviews, key=lambda x: x.get('createdAt', 0), reverse=True)
            time_cutoff = 0
            if days > 0:
                time_cutoff = datetime.now().timestamp() - days * 86400

            for item in interviews_sorted:
                created = item.get('createdAt', 0)
                # 时间过滤
                if days > 0 and created > 0 and created / 1000 < time_cutoff:
                    break  # 已排序，遇到超出范围的直接停止
                title = item.get('title', '')
                raw_url = item.get('url', '')
                link = raw_url.replace('http://', 'https://') if raw_url.startswith('http') else f'https://xueqiu.com{raw_url}'
                ts = datetime.fromtimestamp(created / 1000).strftime('%Y-%m-%d %H:%M') if created else ''
                content = item.get('content', '') or ''
                news_list.append(News(
                    title=title[:200],
                    content=content[:3000],
                    time=ts,
                    source='新闻',
                    link=link,
                ))
            self.logger.info(f"  资讯 API: {len(news_list)} 条")
        except Exception as e:
            self.logger.warning(f"API 爬取资讯失败: {e}")
        return news_list

    def _crawl_notices_via_api(self, symbol: str, max_pages: int = 10, days: int = 0) -> List[Notice]:
        """通过雪球官方 API 爬取公告。

        API: GET https://xueqiu.com/statuses/stock_timeline.json
        params: symbol_id, source=公告, count=10, page=N
        """
        notices = []
        try:
            cookies_path = Path(self.cookies_path)
            if not cookies_path.exists():
                cookies_path = Path(__file__).parent.parent.parent / 'config' / 'cookies' / 'xueqiu.json'
            if cookies_path.exists():
                with open(cookies_path) as f:
                    cookies = json.load(f)
            else:
                self.logger.warning("未找到 cookies，跳过公告爬取")
                return []
            token = next((c['value'] for c in cookies if c['name'] == 'xq_a_token'), None)
            if not token:
                self.logger.warning("未找到 xq_a_token，跳过公告爬取")
                return []
            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
                'Cookie': f'xq_a_token={token}',
                'Referer': f'https://xueqiu.com/S/{symbol}',
                'Accept': 'application/json, text/plain, */*'
            }
            should_stop = False
            time_cutoff = datetime.now().timestamp() - days * 86400 if days > 0 else 0
            for page_num in range(1, max_pages + 1):
                if should_stop:
                    break
                # 港股symbol_id用纯数字(00700)，A股用SH/SZ前缀，其他直接用symbol
                symbol_id_map = {'HK00700': '00700'}
                symbol_id = symbol_id_map.get(symbol, symbol)
                url = (f'https://xueqiu.com/statuses/stock_timeline.json'
                       f'?symbol_id={symbol_id}&count=10&source=%E5%85%AC%E5%91%8A&page={page_num}')
                resp = requests.get(url, headers=headers, timeout=15)
                if resp.status_code != 200:
                    break
                data = resp.json()
                items = data.get('list', [])
                if not items:
                    break
                for item in items:
                    desc = item.get('description', '') or ''
                    # 提取标题：去掉 <a...> 后的链接部分
                    title = re.sub(r'<a[^>]+>.*</a>', '', desc).strip()
                    # 提取链接
                    link_match = re.search(r'href="(https?://[^"]+)"', desc)
                    link = link_match.group(1) if link_match else ''
                    created = item.get('created_at', 0)
                    ts = datetime.fromtimestamp(created / 1000).strftime('%Y-%m-%d') if created else ''
                    # 过滤空标题（SEC文件等description无有效标题时跳过）
                    if not title.strip():
                        self.logger.debug(f"跳过空标题公告: description={desc[:80]}")
                        continue
                    # 时间过滤：遇到超出范围的公告，停止爬取
                    if days > 0 and created > 0 and created / 1000 < time_cutoff:
                        self.logger.info(f"  公告 API 页 {page_num} 遇到 {days} 天前的公告，停止")
                        should_stop = True
                        break
                    notices.append(Notice(
                        title=title[:300],
                        link=link,
                        time=ts,
                    ))
                self.logger.info(f"  公告 API 页 {page_num}: {len(items)} 条 (累计 {len(notices)} 条)")
                if should_stop:
                    break
                if len(items) < 10:
                    break
                self.human_delay(0.5, 1.5)
        except Exception as e:
            self.logger.warning(f"API 爬取公告失败: {e}")
        return notices

    def _parse_items_with_pagination(self, page: Page, max_pages: int = 3,
                                      target_count: int = 30) -> List:
        items = []
        # [Items] Initial fetch -- must run even when max_pages=0
        try:
            items = page.query_selector_all('.timeline__item')
            self.logger.info(f"[Items] Initial fetch: {len(items)} items")
        except Exception as e:
            self.logger.warning(f"[Items] Initial fetch failed: {e}")

        if max_pages <= 0:
            return items

        for page_num in range(1, max_pages + 1):
            try:
                new_items = page.query_selector_all('.timeline__item')
                new_count = len(new_items) - len(items)
                self.logger.info(f"分页 [{page_num}/{max_pages}] 本页新增: {max(new_count, 0)}, 累计: {len(new_items)} 条")
                items = new_items  # DOM已刷新，new_items就是最新全量
                if len(items) >= target_count:
                    break
                # 点击"更多"
                clicked = page.evaluate('''() => {
                    const btns = document.querySelectorAll('button, a, div');
                    for (const btn of btns) {
                        const text = btn.innerText.trim();
                        if (text === '更多' || text === '加载更多' || text.includes('查看更多')) {
                            btn.click();
                            return true;
                        }
                    }
                    return false;
                }''')
                if clicked:
                    self.human_delay(1.5, 3)
                    try:
                        page.wait_for_selector('.timeline__item', timeout=5000)
                    except Exception:
                        pass
            except Exception as e:
                self.logger.warning(f"分页 [{page_num}] 异常: {e}")

        return items

    def _parse_single_discussion(self, item) -> Optional[Discussion]:
        try:
            text = item.inner_text().strip()
            author_match = re.search(r'^([^\d]+?)(?=\d+小时|\d+天|昨天|今天|\d{4}|\d{2}:\d{2}|\d+秒|\d+分钟)', text)
            author = author_match.group(1).strip()[:30] if author_match else ''
            time_match = re.search(r'(\d+秒前|\d+分钟前|\d+小时前|\d+天前|昨天|今天|\d{2}:\d{2}|\d{4}-\d{2}-\d{2})', text)
            time_str = time_match.group(1) if time_match else ''
            content = re.sub(r'^[^\d]+?(\d+秒前|\d+分钟前|\d+小时前|\d+天前|昨天|今天)[^\n]*', '', text)
            content = re.sub(r'展开.*$', '', content, flags=re.MULTILINE)
            content = re.sub(r'转发.*$', '', content, flags=re.MULTILINE)
            content = re.sub(r'赞.*$', '', content, flags=re.MULTILINE)
            content = re.sub(r'收藏.*$', '', content, flags=re.MULTILINE)
            content = content.strip()[:500]

            # 检测专栏：来源=雪球（平台发布的专栏文章）
            is_column = '来自雪球' in text

            link = ''
            for link_elem in item.query_selector_all('a'):
                href = link_elem.get_attribute('href') or ''
                if re.match(r'/\d+/\d+$', href):
                    link = 'https://xueqiu.com' + href
                    break

            if content and len(content) > 10:
                return Discussion(author=author, content=content,
                                  time=time_str, link=link, is_column=is_column)
        except Exception:
            pass
        return None

    def _parse_single_news(self, item) -> Optional[News]:
        """解析资讯条目 — 提取标题和正文内容"""
        try:
            text = item.inner_text().strip()
            if not text or len(text) < 10:
                return None

            # 标题：股票名+日期模式
            # 美股: 携程(TCOM)04-19 21:45
            # A股: 茅台(600519)04-19 15:30
            # 港股: 腾讯(00700)04-19 16:00
            title_match = re.search(
                r'^(.+?\([A-Z0-9]+\)\s*\d{2,4}[-/]\d{2}\s+\d{2}:\d{2})',
                text
            )
            title = title_match.group(1).strip() if title_match else text[:80]

            # 来源
            source_match = re.search(r'来自(新闻|公告|研报|媒体|AI)', text)
            source = source_match.group(1) if source_match else ''

            # 时间：优先匹配日期时间格式
            time_match = re.search(
                r'(\d{4}-\d{2}-\d{2}|\d{2}-\d{2}\s+\d{2}:\d{2}|\d+分钟前|\d+小时前|\d+天前|昨天|今天)',
                text
            )
            time_str = time_match.group(1) if time_match else ''

            # 正文：去掉标题头和来源行后的剩余文字
            content = text
            if title:
                content = content.replace(title, '', 1)
            # 去掉"来自新闻"等噪音
            content = re.sub(r'来自(新闻|公告|研报|媒体|AI)\s*', '', content)
            # 去掉互动统计噪音
            content = re.sub(
                r'[\ue000-\uf8ff\u2000-\u206f]', '', content
            ).strip()
            content = content[:3000]

            # 真正的外部链接（文章详情页，非股票页自身）
            link = ''
            for link_elem in item.query_selector_all('a'):
                href = link_elem.get_attribute('href') or ''
                if href and not href.startswith('javascript'):
                    full = href if href.startswith('http') else 'https://xueqiu.com' + href
                    # 过滤掉回到股票页的链接
                    # 过滤股票页自身链接 (/S/SH600519, /S/BABA 等)
                    if not re.search(r'/S/[A-Z0-9]+$', full):
                        link = full
                        break

            return News(title=title[:200], content=content, time=time_str,
                        source=source, link=link)
        except Exception:
            pass
        return None

    def _parse_notices(self, page: Page) -> List[Notice]:
        notices = []
        try:
            time.sleep(1)
            items = page.evaluate('''() => {
                const items = [];
                const timelineItems = document.querySelectorAll('.timeline__item');
                for (const item of timelineItems) {
                    const text = item.innerText || '';
                    const links = item.querySelectorAll('a');
                    let link = '';
                    for (const a of links) {
                        const href = a.getAttribute('href') || '';
                        if (href && !href.startsWith('javascript')) {
                            link = href.startsWith('http') ? href : 'https://xueqiu.com' + href;
                        }
                    }
                    if (text.trim()) items.push({ title: text.trim().substring(0, 200), link: link });
                }
                return items;
            }''')

            for item_data in items:
                notice = Notice(
                    title=item_data.get('title', ''),
                    link=item_data.get('link', ''),
                )
                # 提取时间
                time_match = re.search(r'(\d+分钟前|\d+小时前|\d+天前|昨天|今天|\d{2}:\d{2}|\d{4}-\d{2}-\d{2}|\d{2}-\d{2}\s+\d{2}:\d{2})', notice.title)
                if time_match:
                    notice.time = time_match.group(1)
                # 提取公告类型
                type_match = re.search(r'\[(.+?)\]', notice.title)
                if type_match:
                    notice.notice_type = type_match.group(1)
                notices.append(notice)

            self.logger.info(f"解析公告: 找到 {len(notices)} 条")
        except Exception as e:
            self.logger.warning(f"解析公告失败: {e}")
        return notices

    def _crawl_news_detail(self, browser, url: str) -> Optional[dict]:
        """爬取新闻/资讯详情页正文

        URL 格式: https://xueqiu.com/talks/item/{id}
        与文章详情页结构相同，可复用 CSS selector 逻辑。
        """
        try:
            page = browser.new_page()
            page.goto(url, timeout=self.timeout)
            self.human_delay(2, 4)
            self._close_modal(page)

            title = page.evaluate('''() => {
                const el = document.querySelector('.article__bd__title, h1.title, .news-title');
                return el ? el.innerText.trim() : document.title;
            }''')
            content = page.evaluate('''() => {
                const selectors = [
                    '.article__bd__detail',
                    '.article-content',
                    '.news-content',
                    '[class*="article-detail"]',
                    '[class*="detail_body"]',
                    '.stock-news-content',
                ];
                for (const sel of selectors) {
                    const el = document.querySelector(sel);
                    if (el && el.innerText.trim().length > 20) {
                        return el.innerText.trim();
                    }
                }
                // fallback: 最长段落
                const paras = document.querySelectorAll('p, div.article-text');
                let best = '';
                for (const p of paras) {
                    const t = p.innerText.trim();
                    if (t.length > best.length) best = t;
                }
                return best;
            }''')
            page.close()
            return {'title': title, 'content': content} if content else None
        except Exception as e:
            self.logger.warning(f"资讯详情爬取失败 {url}: {e}")
            try:
                page.close()
            except Exception:
                pass
            return None


    def _crawl_notice_pdf_text(self, url: str) -> Optional[str]:
            """下载雪球公告 PDF 并提取正文文本
    
            优先用 pymupdf(fitz)，若提取文字 <200 字则尝试 pdfplumber 回退。
            """
            import urllib.request, io
    
            # 下载 PDF
            try:
                req = urllib.request.Request(
                    url,
                    headers={
                        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
                        'Referer': 'https://xueqiu.com/',
                    }
                )
                with urllib.request.urlopen(req, timeout=30) as resp:
                    pdf_data = resp.read()
            except Exception as e:
                self.logger.warning(f"公告 PDF 下载失败 {url}: {e}")
                return None
    
            full_text = None
    
            # Method 1: fitz
            if fitz:
                try:
                    doc = fitz.open(stream=pdf_data, filetype='pdf')
                    texts = []
                    for page in doc:
                        text = page.get_text()
                        if text.strip():
                            texts.append(text.strip())
                    doc.close()
                    full_text = '\n'.join(texts)
                    self.logger.debug(f"fitz 提取: {len(full_text)} 字")
                    if len(full_text) < 200:
                        self.logger.debug(f"  fitz 提取过短({len(full_text)}字)，尝试 pdfplumber")
                        full_text = None  # trigger fallback
                except Exception as e:
                    self.logger.debug(f"fitz 解析异常: {e}")
                    full_text = None
    
            # Method 2: pdfplumber fallback
            if not full_text:
                try:
                    import pdfplumber
                    with pdfplumber.open(io.BytesIO(pdf_data)) as pdf:
                        texts = []
                        for page in pdf.pages:
                            t = page.extract_text()
                            if t and t.strip():
                                texts.append(t.strip())
                    full_text = '\n'.join(texts)
                    self.logger.debug(f"pdfplumber 提取: {len(full_text)} 字")
                except ImportError:
                    self.logger.debug("pdfplumber 未安装")
                except Exception as e:
                    self.logger.debug(f"pdfplumber 解析异常: {e}")
    
            if not full_text or not full_text.strip():
                return None
    
            # 截断超长内容
            if len(full_text) > 8000:
                full_text = full_text[:8000] + '\n[...PDF正文已截断...]'
            return full_text
    def _crawl_article_detail(self, page: Page, url: str) -> Optional[Article]:
        """爬取雪球文章详情

        优先使用 ScrapingExtractor（DeepSeek LLM）提取正文，
        失败时回退到原有 CSS selector 逻辑。
        """
        try:
            detail_page = page.context.new_page()
            detail_page.goto(url, timeout=30000)
            time.sleep(2)
            self._close_modal(detail_page)

            # ── Phase 1: DeepSeek LLM 提取 ───────────────────────────
            raw_html = detail_page.content()
            result = self.extractor.extract(url, raw_html=raw_html)

            if result.is_valid():
                # 解析 symbols（可能是 JSON 字符串或列表）
                import json as _json
                try:
                    symbols = _json.loads(result.symbols) if isinstance(result.symbols, str) else result.symbols
                    if not isinstance(symbols, list):
                        symbols = []
                except Exception:
                    symbols = []
                article_id = url.rstrip('/').split('/')[-1] if '/' in url else ''
                detail_page.close()
                return Article(
                    title=result.title[:200] if result.title else '',
                    author=result.author,
                    content=result.content[:10000],
                    time=result.time,
                    link=url,
                    article_id=article_id,
                )

            # ── Phase 2: Fallback 原有 CSS selector ──────────────────
            title = detail_page.evaluate('''() => {
                const h1 = document.querySelector('.article__bd__title');
                return h1 ? h1.innerText.trim() : document.title;
            }''')
            author = detail_page.evaluate('''() => {
                const el = document.querySelector('.article__bd__from a, .user-name, [class*="author"]');
                return el ? el.innerText.trim() : '';
            }''')
            time_str = detail_page.evaluate('''() => {
                const el = document.querySelector('.article__bd__time, [class*="date"], time');
                return el ? el.innerText.trim() : '';
            }''')
            content = detail_page.evaluate('''() => {
                const article = document.querySelector('.article__bd__detail');
                return article ? article.innerText.trim() : '';
            }''')
            detail_page.close()

            if content and len(content) > 50:
                article_id = url.rstrip('/').split('/')[-1] if '/' in url else ''
                return Article(
                    title=title[:200],
                    author=author,
                    content=content[:10000],
                    time=time_str,
                    link=url,
                    article_id=article_id,
                )
        except Exception:
            try:
                detail_page.close()
            except Exception:
                pass
        return None

    def _extract_notice_summary_from_title(self, notice) -> str:
        """从公告 title 提取结构化摘要（用于 SEC EDGAR 公告）"""
        t = notice.title or ''
        parts = []
        type_map = {
            '20-F': '年度财报(20-F)',
            '6-K': '境外发行人报告(6-K)',
            'SCHEDULE 13G': '大股东持股声明(13G)',
            '13G/A': '大股东持股变动(13G/A)',
            '4 ': '内部人交易(Form 4)',
            '3 ': '首次持股声明(Form 3)',
        }
        for k, v in type_map.items():
            if k in t.upper() or k in t:
                parts.append(v)
                break
        if not parts:
            parts.append(notice.notice_type or '公告')
        size_match = re.search(r'Size:\s*([\d.]+\s*(?:KB|MB|GB)?)', t)
        if size_match:
            parts.append(f'文件大小: {size_match.group(1).strip()}')
        if notice.time:
            parts.append(f'日期: {notice.time}')
        return ' | '.join(parts)

    def _crawl_notice_detail(self, page: Page, url: str) -> Optional[dict]:
        """爬取雪球内部公告详情页（非 SEC 链接）"""
        try:
            detail_page = page.context.new_page()
            detail_page.goto(url, timeout=30000)
            time.sleep(3)
            self._close_modal(detail_page)
            result = detail_page.evaluate('''() => {
                const selectors = [
                    '.announcement-detail__content',
                    '.stock-notice-content',
                    '.article__bd__detail',
                    '[class*="notice-detail"]',
                ];
                let content = '';
                for (const sel of selectors) {
                    const el = document.querySelector(sel);
                    if (el && el.innerText.trim().length > 20) {
                        content = el.innerText.trim();
                        break;
                    }
                }
                let pdfLink = '';
                const links = document.querySelectorAll('a');
                for (const link of links) {
                    const href = link.getAttribute('href') || '';
                    if (href.includes('.pdf')) { pdfLink = href; break; }
                }
                if (!pdfLink) {
                    const m = window.location.href.match(/xueqiu\\.com\\/S\\/(\\w+)\\/(\\d+)/);
                    if (m) pdfLink = 'https://stockn.xueqiu.com/' + m[1] + '/' + m[2] + '.pdf';
                }
                return { content: content.substring(0, 5000), pdf_link: pdfLink };
            }''')
            detail_page.close()
            return result
        except Exception:
            try:
                detail_page.close()
            except Exception:
                pass
        return None

    # ========== 序列化 ==========

    def save(self, result: CrawlResult, path: str):
        """保存 CrawlResult 为 JSON"""
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(result.to_dict(), f, ensure_ascii=False, indent=2)
        self.logger.info(f"数据已保存: {path}")

    @classmethod
    def load(cls, path: str) -> CrawlResult:
        """从 JSON 加载 CrawlResult"""
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return CrawlResult.from_dict(data)
