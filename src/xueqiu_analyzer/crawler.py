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
from pathlib import Path
from typing import List, Optional, Tuple

try:
    from playwright.sync_api import sync_playwright, Page, BrowserContext
except ImportError:
    raise ImportError("请安装 playwright: pip install playwright && playwright install chromium")

from .models import (
    CrawlResult, Discussion, News, Notice, Article,
)
from .extractor import ScrapingExtractor

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_DIR = os.path.expanduser('~/.xueqiu_crawler')


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
              max_articles: int = 10) -> CrawlResult:
        """
        爬取股票详情页数据

        Args:
            symbol: 股票代码
            max_pages: 最大分页数
            max_articles: 最大文章数

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
                url = f'https://xueqiu.com/S/{symbol}'
                self.logger.info(f"访问股票详情页: {url}")
                page.goto(url, timeout=self.timeout)
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
                self.logger.info("=== 爬取讨论 ===")
                if self._switch_tab(page, '讨论'):
                    all_items = self._parse_items_with_pagination(
                        page, max_pages=max_pages, target_count=30)
                    for item in all_items[:30]:
                        try:
                            disc = self._parse_single_discussion(item)
                            if disc:
                                result.discussions.append(disc)
                        except Exception:
                            pass
                    self.logger.info(f"获取 {len(result.discussions)} 条讨论")

                # ========== 爬取资讯 ==========
                self.logger.info("=== 爬取资讯 ===")
                if self._switch_tab(page, '资讯'):
                    all_items = self._parse_items_with_pagination(
                        page, max_pages=max_pages, target_count=30)
                    for item in all_items[:30]:
                        try:
                            news = self._parse_single_news(item)
                            if news:
                                result.news.append(news)
                        except Exception:
                            pass
                    self.logger.info(f"获取 {len(result.news)} 条资讯")

                    # 爬取资讯详情（仅对真正的文章链接，过滤股票页自身链接）
                    if result.news:
                        import re as _re
                        news_with_link = [
                            n for n in result.news
                            if n.link and not _re.search(r'/S/[A-Z0-9]+$', n.link)
                        ]
                        if news_with_link:
                            self.logger.info("爬取资讯详情...")
                            for i, n in enumerate(news_with_link[:15]):
                                try:
                                    self.logger.info(f"  [{i+1}/{len(news_with_link)}] {n.title[:40]}...")
                                    detail_page = browser.new_page()
                                    detail_page.goto(n.link, timeout=self.timeout)
                                    self.human_delay(2, 3)
                                    self._close_modal(detail_page)
                                    # 多选择器兼容新旧版雪球文章页
                                    content = detail_page.evaluate('''() => {
                                        const selectors = [
                                            '.article__bd__detail',
                                            '.detail-content',
                                            '.article-content',
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
                                        // fallback: 取可见文本中最长的段落
                                        const paras = document.querySelectorAll('p, div.article-text');
                                        let best = '';
                                        for (const p of paras) {
                                            const t = p.innerText.trim();
                                            if (t.length > best.length) best = t;
                                        }
                                        return best;
                                    }''')
                                    if content and len(content) > 20:
                                        # 检查是否为免责声明/无用内容
                                        if _is_disclaimer(content):
                                            self.logger.debug(f"    跳过免责声明 ({len(content)}字)")
                                            n.content = ""
                                            n.link = ""  # 后续质量检测可以识别
                                        else:
                                            n.content = content[:5000]
                                            self.logger.debug(f"    获取到 {len(content)} 字正文")
                                    detail_page.close()
                                except Exception:
                                    try:
                                        detail_page.close()
                                    except Exception:
                                        pass

                # ========== 爬取公告 ==========
                self.logger.info("=== 爬取公告 ===")
                if self._switch_tab(page, '公告'):
                    notices = self._parse_notices(page)
                    result.notices = notices
                    self.logger.info(f"获取 {len(notices)} 条公告")

                    # 公告详情：SEC 用 title 摘要，雪球内部用页面提取
                    for nt in notices:
                        if not nt.link:
                            continue
                        if 'sec.gov' in nt.link:
                            nt.content = self._extract_notice_summary_from_title(nt)
                        else:
                            try:
                                detail = self._crawl_notice_detail(page, nt.link)
                                if detail:
                                    nt.content = detail.get('content', '')
                                    nt.pdf_link = detail.get('pdf_link', '')
                            except Exception:
                                pass

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

    def _parse_items_with_pagination(self, page: Page, max_pages: int = 3,
                                      target_count: int = 30) -> List:
        items = []
        for page_num in range(1, max_pages + 1):
            try:
                new_items = page.query_selector_all('.timeline__item')
                new_count = len(new_items) - len(items)
                self.logger.info(f"分页 [{page_num}] 本页新增: {max(new_count, 0)}, 累计: {len(new_items)} 条")
                items = new_items
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
                else:
                    break
            except Exception:
                break
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

            link = ''
            for link_elem in item.query_selector_all('a'):
                href = link_elem.get_attribute('href') or ''
                if re.match(r'/\d+/\d+$', href):
                    link = 'https://xueqiu.com' + href
                    break

            if content and len(content) > 10:
                return Discussion(author=author, content=content,
                                  time=time_str, link=link)
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
