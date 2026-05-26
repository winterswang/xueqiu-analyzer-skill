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

                # ========== 爬取讨论 (最新) ==========
                self.logger.info("=== 爬取讨论(最新) ===")
                if self._switch_tab(page, '讨论'):
                    self.human_delay(1, 2)
                    self._crawl_items_with_pagination(
                        page, self._parse_single_discussion,
                        result.discussions, max_pages=max_pages, target_count=5000)
                    self.logger.info(f"获取 {len(result.discussions)} 条讨论")

                # ========== 爬取资讯 ==========
                self.logger.info("=== 爬取资讯 ===")
                if self._switch_tab(page, '资讯'):
                    self._crawl_items_with_pagination(
                        page, self._parse_single_news,
                        result.news, max_pages=max_pages, target_count=5000)
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
                    # 公告数量少，只需第一页10条，不翻页
                    items = page.query_selector_all('.timeline__item')
                    for item in items[:20]:
                        try:
                            nt = self._parse_single_notice(item)
                            if nt:
                                result.notices.append(nt)
                        except Exception:
                            pass
                    self.logger.info(f"获取 {len(result.notices)} 条公告")

                    # 公告详情：SEC 摘要、雪球内部页面提取
                    for nt in result.notices:
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

                # ========== 专栏文章分离 ==========
                # 从讨论中分离出 true 专栏文章
                # 规则：content 以「【专栏」开头 + 非回复（不以"回复"开头）+ 正文够长
                true_discussions = []
                for d in result.discussions:
                    content = (d.content or '').strip()
                    if content.startswith('【专栏') and '专栏' in content[:30]:
                        end = content.find('】')
                        body = content[end+1:].lstrip('\n').strip() if end > 0 else ''
                        # Reply patterns: starts with "回复@", "//@", or very short
                        is_reply = (body.startswith('回复')
                                    or body.startswith('//@')
                                    or len(body) < 80)
                        if is_reply:
                            true_discussions.append(d)
                            continue
                        title = content[1:end].strip() if end > 0 else content[:50]
                        result.articles.append(Article(
                            title=title,
                            author=d.author,
                            content=body[:5000],
                            time=d.time,
                            link=d.link,
                            article_id=d.link.split('/')[-1] if d.link else '',
                        ))
                    else:
                        true_discussions.append(d)
                col_count = len(result.articles)
                if col_count:
                    self.logger.info(f"分离 {col_count} 篇专栏文章 → articles")
                result.discussions = true_discussions

                # Clean up residual 【专栏xxx】 or 专栏xxx prefix from discussions that are replies
                for d in result.discussions:
                    stripped = d.content
                    if stripped.startswith('【专栏'):
                        end = stripped.find('】')
                        if end > 0:
                            stripped = stripped[end+1:].lstrip('\n').strip()
                    elif stripped.startswith('专栏') and len(stripped) > 4 and not stripped[2:4].isalpha():
                        # Edge case: content starts with "专栏xxx" without 【】
                        end = stripped.find('\n')
                        if end > 0:
                            stripped = stripped[end:].lstrip('\n').strip()
                    d.content = stripped

                # ========== 丰富详情（讨论+专栏文章+评论+正文） ==========
                self.logger.info(f"\n爬取 {max_articles} 条详情富化...")
                # Collect links: articles first (higher value), then discussions
                detail_links = []
                for art in result.articles:
                    if art.link and re.match(r'https://xueqiu\.com/\d+/\d+', art.link):
                        detail_links.append(('art', art, art.link))
                for disc in result.discussions:
                    if disc.link and re.match(r'https://xueqiu\.com/\d+/\d+', disc.link):
                        detail_links.append(('disc', disc, disc.link))
                if len(detail_links) < max_articles:
                    for n in result.news:
                        if n.link and re.match(r'https://xueqiu\.com/\d+/\d+', n.link):
                            detail_links.append(('news', n, n.link))

                seen = set()
                enriched_disc = 0
                enriched_art = 0
                for kind, obj, link in detail_links[:max_articles]:
                    if link in seen:
                        continue
                    seen.add(link)
                    try:
                        detail = self._crawl_discussion_detail(page, link)
                        if not detail:
                            continue
                        if kind == 'art':
                            if detail.get('full_content') and len(detail['full_content']) > len(obj.content):
                                obj.content = detail['full_content'][:5000]
                            if detail.get('comments'):
                                obj.comments = detail.get('comments', [])
                            obj.comment_count = detail.get('comment_count', 0)
                            enriched_art += 1
                        elif kind == 'disc':
                            if detail.get('full_content') and len(detail['full_content']) > len(obj.content):
                                obj.content = detail['full_content'][:2000]
                            if detail.get('comments'):
                                obj.comments = detail['comments']
                            enriched_disc += 1
                        # kind == 'news': skip, already handled separately
                    except Exception:
                        pass

                if enriched_disc or enriched_art:
                    self.logger.info(f"  丰富 {enriched_disc} 条讨论, {enriched_art} 篇专栏")

                # 保存 cookies
                self._save_cookies(context)

            finally:
                browser.close()

        self.logger.info(f"爬取完成: {len(result.discussions)} 讨论, "
                         f"{len(result.articles)} 专栏, "
                         f"{len(result.news)} 资讯, "
                         f"{len(result.notices)} 公告")
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

    def _switch_sub_tab(self, page: Page, sub_tab_name: str) -> bool:
        """Switch to a sub-tab within the current tab.
        
        Discussion tab has sub-tabs: 新帖, 热帖, 关注
        """
        return self._js_click(page, sub_tab_name)

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

    def _crawl_items_with_pagination(self, page: Page, parse_fn: callable,
                                       result_list: list, max_pages: int = 100,
                                       target_count: int = 1000):
        """Navigate pages, parse items on each page, accumulate into result_list.

        Time-aware stop: when items start showing '昨天' or date patterns (not 'today'),
        we've crossed into the previous day and stop crawling.
        """
        seen_content = set()
        stale_pages = 0

        for page_num in range(1, max_pages + 1):
            try:
                # Scroll to load lazy images/etc.
                page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                self.human_delay(0.5, 1)

                # Parse current page items
                items = page.query_selector_all('.timeline__item')
                parsed_this_page = 0

                for item in items:
                    try:
                        obj = parse_fn(item)
                        if obj:
                            # Dedup by content signature (first 50 chars)
                            sig = (getattr(obj, 'content', '') or getattr(obj, 'title', ''))[:50]
                            if sig and sig not in seen_content:
                                seen_content.add(sig)
                                result_list.append(obj)
                                parsed_this_page += 1
                    except Exception:
                        pass

                self.logger.info(f"分页 [{page_num}] 本页: {parsed_this_page} 条, 累计: {len(result_list)}")

                # ── Time-based stop: check if any parsed item is from 'yesterday' or earlier ──
                crossed_day = False
                for obj in result_list[-parsed_this_page:] if parsed_this_page else []:
                    t = getattr(obj, 'time', '')
                    if not t:
                        continue
                    # Today indicators: X秒前, X分钟前, X小时前, 今天
                    if re.search(r'(秒前|分钟前|小时前|今天)', t):
                        continue
                    # Yesterday or date patterns: 昨天, MM-DD, YYYY-MM-DD, HH:MM (no '前')
                    if re.search(r'(昨天|\d{2}-\d{2}|\d{4}-\d{2}-\d{2})', t):
                        crossed_day = True
                        # Keep '昨天' items too (they may still be today's late posts)
                        # Only stop if we see 2+昨天 items in the same page
                        yesterday_count = sum(1 for o in result_list[-parsed_this_page:] 
                                              if '昨天' in (getattr(o, 'time', '') or ''))
                        if yesterday_count >= 3:
                            self.logger.info(f"  时间已跨到昨天({yesterday_count}条), 停止")
                            return

                # Stop conditions
                if len(result_list) >= target_count:
                    self.logger.info(f"  已达标 {target_count} 条, 停止")
                    break
                if parsed_this_page == 0:
                    stale_pages += 1
                else:
                    stale_pages = 0
                if stale_pages >= 3:
                    self.logger.info(f"  连续 {stale_pages} 页无新数据, 停止")
                    break

                # Navigate to next page
                clicked = page.evaluate('''() => {
                    const all = document.querySelectorAll('a, button, div, span');
                    for (const btn of all) {
                        const text = (btn.innerText || '').trim();
                        if (text === '下一页') {
                            btn.click();
                            return true;
                        }
                    }
                    return false;
                }''')

                if clicked:
                    self.human_delay(1.5, 3)
                else:
                    self.logger.info(f"  未找到'下一页', 停止")
                    break

            except Exception:
                pass

    def _parse_items_with_pagination(self, page: Page, max_pages: int = 10,
                                      target_count: int = 100) -> List:
        """Deprecated: use _crawl_items_with_pagination instead."""
        return page.query_selector_all('.timeline__item')

    def _parse_single_discussion(self, item) -> Optional[Discussion]:
        """Parse discussion item from timeline DOM element.

        Uses JS evaluate() for structured extraction instead of regex on inner_text().
        Extracts: author, time, heading(column title), content, interactions, link.
        """
        try:
            # Structured extraction via JS (evaluate on the element handle)
            data = item.evaluate('''(el) => {
                const result = {author: '', time: '', title: '', content: '',
                                link: '', comments: 0, likes: 0, forwards: 0};

                // 1) Author: first <a> that is NOT a stock symbol ($xxx), NOT a time string
                const links = el.querySelectorAll('a');
                for (const a of links) {
                    const txt = a.innerText.trim();
                    if (!txt) continue;
                    // Skip stock symbols, time strings, icon-only, interaction numbers
                    if (/^[$＄]/.test(txt)) continue;
                    if (/(分钟前|小时前|天前|昨天|今天|来自|修改于)/.test(txt)) continue;
                    if (/^[\\ue000-\\uf8ff]+$/.test(txt)) continue;
                    if (/^(收起|展开|转发|讨论|赞|收藏|分享).*$/.test(txt)) continue;
                    if (/^\\d+$/.test(txt)) continue;
                    // First valid-looking username (no spaces, < 30 chars)
                    if (txt.length >= 2 && txt.length < 30) {
                        result.author = txt;
                        break;
                    }
                }

                // 2) Time: from any link containing time pattern
                for (const a of links) {
                    const txt = a.innerText.trim();
                    if (/(\\d+秒前|\\d+分钟前|\\d+小时前|\\d+天前|昨天|今天|修改于|来自)/.test(txt)) {
                        const m = txt.match(/(\\d+秒前|\\d+分钟前|\\d+小时前|\\d+天前|昨天|今天|修改于\\d+.*?前|[0-9]{2}:[0-9]{2})/);
                        result.time = m ? m[1] : txt.slice(0, 20);
                        break;
                    }
                }

                // 3) Column article title: h3 or heading element
                const h = el.querySelector('h3, h2, [class*="title"]');
                if (h && !/(收起|展开)/.test(h.innerText)) {
                    result.title = h.innerText.trim();
                }

                // 4) Content: the article body, excluding chrome
                const bodySelectors = [
                    '.article__bd__detail',
                    '.detail-body',
                    '[class*="content"]:not([class*="title"])',
                ];
                let body = '';
                for (const sel of bodySelectors) {
                    const b = el.querySelector(sel);
                    if (b && b.innerText.trim().length > 20) {
                        body = b.innerText.trim();
                        break;
                    }
                }

                // Fallback: use inner_text minus chrome
                if (!body) {
                    body = el.innerText;
                    // Remove author line
                    if (result.author) {
                        body = body.replace(new RegExp(result.author + '[\\s\\S]*?(分钟前|小时前|天前|来自)', 'm'), '');
                    }
                    // Remove quote/collapse headers
                    body = body.replace(/^收起\\s*\\n/gm, '');
                    body = body.replace(/^展开\\s*\\n/gm, '');
                    // Remove interaction row
                    body = body.replace(/[\\ue000-\\uf8ff]\\s*(转发|讨论|赞|收藏)\\s*\\d*/g, '');
                    body = body.replace(/分享\\s*\\n/g, '');
                    body = body.trim();
                }

                result.content = body.slice(0, 2000);

                // 5) Link: article detail URL
                for (const a of links) {
                    const href = a.getAttribute('href') || '';
                    if (/\\/\\d+\\/\\d+$/.test(href)) {
                        result.link = 'https://xueqiu.com' + href;
                        break;
                    }
                }

                // 6) Interactions: from the row with icon + count
                const text = el.innerText;
                let m = text.match(/讨论\\s*(\\d+)/);
                if (m) result.comments = parseInt(m[1]);
                m = text.match(/赞\\s*(\\d+)/);
                if (m) result.likes = parseInt(m[1]);
                m = text.match(/转发\\s*(\\d+)/);
                if (m) result.forwards = parseInt(m[1]);

                return result;
            }''')

            content = (data.get('content') or '').strip()
            if len(content) < 5:
                return None

            # If there's a column title, prepend it
            if data.get('title') and '专栏' in data['title']:
                content = f"【{data['title']}】\n{content}"

            return Discussion(
                author=data.get('author', ''),
                content=content,
                time=data.get('time', ''),
                link=data.get('link', ''),
                comment_count=data.get('comments', 0),
                forward_count=data.get('forwards', 0),
                like_count=data.get('likes', 0),
            )
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

    def _parse_single_notice(self, item) -> Optional[Notice]:
        """Parse a single notice from timeline DOM element."""
        try:
            text = item.inner_text().strip()
            if not text:
                return None

            # Get link
            link = ''
            links = item.query_selector_all('a')
            for a in links:
                href = a.get_attribute('href') or ''
                if href and not href.startswith('javascript'):
                    link = 'https://xueqiu.com' + href if href.startswith('/') else href
                    break

            # Clean title
            clean_title = re.sub(r'[\ue000-\uf8ff\u2000-\u206f]', '', text).strip()[:200]

            notice = Notice(
                title=clean_title,
                link=link,
            )

            # Extract time
            time_match = re.search(r'(\d+秒前|\d+分钟前|\d+小时前|\d+天前|昨天|今天|\d{2}:\d{2}|\d{4}-\d{2}-\d{2}|\d{2}-\d{2}\s+\d{2}:\d{2})', clean_title)
            if time_match:
                notice.time = time_match.group(1)

            # Extract notice type
            type_match = re.search(r'\[(.+?)\]', clean_title)
            if type_match:
                notice.notice_type = type_match.group(1)
            else:
                notice.notice_type = _detect_notice_type(clean_title)

            return notice
        except Exception:
            pass
        return None


# ── Notice type detection ────────────────────────────────────

_NOTICE_TYPE_A = re.compile(
    r'关于(.+?)(?:的|之)(公告|通知|决议|报告|议案|说明|提示|批复|意见)'
)
_NOTICE_TYPE_SEC = re.compile(
    r'(?:Statement|Report)\s+(?:of|on)\s+(.+?)(?:\s+Accession|\s+Size|$)',
    re.IGNORECASE
)
_NOTICE_TYPE_SEC_FORM = re.compile(
    r'(Form\s+[\d\-A-Z]+)', re.IGNORECASE
)


def _detect_notice_type(title: str) -> str:
    """Detect notice type from title when bracket format [type] is absent.

    Covers A-share (\"关于...的公告\") and SEC filing (\"Statement of...\") formats.
    """
    # A-share: 关于聘任董事会秘书的公告 → "聘任董事会秘书公告"
    m = _NOTICE_TYPE_A.search(title)
    if m:
        return f'{m.group(1).strip()}{m.group(2)}'[:60]

    # SEC: "Statement of changes in beneficial ownership"
    m = _NOTICE_TYPE_SEC.search(title)
    if m:
        return f'SEC: {m.group(1).strip()}'[:60]

    # SEC Form: "Form 4", "Form 144"
    m = _NOTICE_TYPE_SEC_FORM.search(title)
    if m:
        return m.group(1)[:60]

    return ''


    def _crawl_discussion_detail(self, page: Page, url: str) -> Optional[dict]:
        """Crawl discussion/article detail page to enrich discussion data.
        
        Extracts:
          - title: column article title (h1 or .article__bd__title)
          - full_content: full article body (not truncated to 500 chars)
          - comments: list of comment texts
        """
        try:
            detail_page = page.context.new_page()
            detail_page.goto(url, timeout=30000)
            try:
                detail_page.wait_for_load_state('networkidle', timeout=10000)
            except Exception:
                pass
            time.sleep(3)
            self._close_modal(detail_page)
            time.sleep(1)  # let page settle after modal close

            # Title: column article heading
            title = detail_page.evaluate('''() => {
                const selectors = [
                    '.article__bd__title',
                    'h1.article__title',
                    '.article-title',
                    '.kb-article-title',
                    '[class*="article-title"]',
                    '[class*="article__title"]',
                    'h1',
                ];
                for (const sel of selectors) {
                    const el = document.querySelector(sel);
                    if (el && el.innerText.trim().length > 2) {
                        return el.innerText.trim();
                    }
                }
                const og = document.querySelector('meta[property="og:title"]');
                if (og) return og.getAttribute('content').trim();
                return '';
            }''')

            # Full content — try multiple selectors, fallback to body
            full_content = detail_page.evaluate('''() => {
                const selectors = [
                    '.article__bd__detail',
                    '.detail-content',
                    '.article-content',
                    '[class*="article-detail"]',
                    '[class*="detail_body"]',
                    '[class*="kb-article"]',
                    '[class*="article-body"]',
                    '[class*="article__bd"]',
                ];
                for (const sel of selectors) {
                    const el = document.querySelector(sel);
                    if (el && el.innerText.trim().length > 50) {
                        return el.innerText.trim();
                    }
                }
                // Last resort: body text (strip nav/footer noise)
                const body = document.body;
                if (body && body.innerText.trim().length > 100) {
                    return body.innerText.trim();
                }
                return '';
            }''')

            # Comments: extract from comment section
            comments = detail_page.evaluate('''() => {
                const results = [];
                const selectors = [
                    '.comment-item',
                    '.comment__item',
                    '[class*="comment-item"]',
                    '.reply-item',
                ];
                for (const sel of selectors) {
                    const items = document.querySelectorAll(sel);
                    for (const item of items) {
                        const text = item.innerText.trim();
                        if (text && text.length > 5 && text.length < 2000) {
                            results.push(text);
                        }
                    }
                    if (results.length > 0) break;
                }
                return results.slice(0, 30);  // limit to 30 most recent
            }''')

            detail_page.close()

            # Filter out disclaimer content
            if full_content and _is_disclaimer(full_content):
                full_content = ''

            detail = {}
            if title and len(title) > 3:
                detail['title'] = title[:200]
            if full_content and len(full_content) > 50:
                detail['full_content'] = full_content[:5000]
            if comments:
                detail['comments'] = comments

            return detail if detail else None
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
