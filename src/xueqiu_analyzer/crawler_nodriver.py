"""XueqiuNodriverCrawler — nodriver 版股票页爬虫

绕过阿里云 WAF 滑动验证，替代 playwright 引擎。
经控制变量实验证实：同一目标页 /S/SH600519，nodriver 抓到真实讨论，
playwright 撞"滑动验证页面"。根因是浏览器引擎反检测能力。

设计参考：xueqiu-crawler/scripts/crawler_nodriver.py 的经典结构
  - nodriver 浏览器管理（真实 Chrome + CDP）
  - _detect_waf() WAF 检测
  - WafDetectedError 异常
  - 会话预热 _warmup（首页→模拟滚动→再进详情页）

与 crawler-nodriver 差异：那个爬用户专栏 /u/<id>，本模块爬股票讨论页
/S/<symbol>，需抓 4 类数据（discussions/news/notices/articles）。

接口对齐 XueqiuCrawler.crawl(symbol, ...) -> CrawlResult，
供 monitor 的 _crawl_with_timeout 优先调用，失败回退 playwright。
"""
from __future__ import annotations

import asyncio
import logging
import random
import re
import time
from datetime import datetime
from typing import List, Optional

try:
    import nodriver as uc
except ImportError:  # pragma: no cover
    uc = None

from .models import CrawlResult, Discussion, News, Notice, Article
from .waf import has_waf_marker

logger = logging.getLogger(__name__)


# ── WAF 检测（正文标记复用 waf.PAGE_MARKERS 唯一实现）──
_WAF_TITLE_PATTERNS = ("滑动验证", "405", "403")


class WafDetectedError(Exception):
    """命中 WAF 拦截页（滑块或重定向）时抛出。"""


# ════════════════════════════════════════════════════════
# PUA 清洗（复用 crawler 的思路）
# ════════════════════════════════════════════════════════
def _clean_pua(text: str) -> str:
    if not text:
        return text
    return "".join(c for c in text if not (0xE000 <= ord(c) <= 0xF8FF))


# ════════════════════════════════════════════════════════
# 纯函数解析器（从 playwright crawler 的 _parse_single_* 移植，
# 改为接收 (text, links) 而非 playwright item 对象）
# ════════════════════════════════════════════════════════
def _parse_date_source(date_source: str):
    """解析 '.date-and-source' 文本: '9秒前· 来自Android' → (time_str, source)。"""
    ds = (date_source or "").strip()
    src_match = re.search(r"·\s*来自(\S+)", ds)
    source = src_match.group(1).strip() if src_match else ""
    time_part = ds[: src_match.start()] if src_match else ds
    _TIME_RE = r"(\d+秒前|\d+分钟前|\d+小时前|\d+天前|昨天\s*\d{0,2}:?\d{0,2}|今天|\d{4}-\d{2}-\d{2}|\d{2}-\d{2}\s+\d{2}:\d{2}|\d{2}:\d{2})"
    tm = re.search(_TIME_RE, time_part)
    time_str = tm.group(1).strip() if tm else time_part.strip()
    return time_str, source


def _split_meta_line(text: str):
    """回退解析（无结构化字段时）：从 innerText 首行推断 meta。

    首行结构: '<作者/股票名><时间>· 来自<平台>'。
    返回 (meta_line, body, author, time_str, source)。
    """
    text = (text or "").strip()
    lines = text.split("\n")
    meta_line = lines[0] if lines else ""
    body_lines = lines[1:] if len(lines) > 1 else []
    body = "\n".join(body_lines).strip()

    src_anchor = re.search(r"·\s*来自", meta_line)
    time_search_scope = meta_line[: src_anchor.start()] if src_anchor else meta_line
    _TIME_RE = r"(\d+秒前|\d+分钟前|\d+小时前|\d+天前|昨天\s*\d{0,2}:?\d{0,2}|今天|\d{4}-\d{2}-\d{2}|\d{2}-\d{2}\s+\d{2}:\d{2}|\d{2}:\d{2})"
    time_matches = list(re.finditer(_TIME_RE, time_search_scope))
    time_match = time_matches[-1] if time_matches else None
    time_str = time_match.group(1).strip() if time_match else ""

    src_match = re.search(r"·\s*来自(\S+)", meta_line)
    source = src_match.group(1).strip() if src_match else ""

    author = meta_line
    if time_match:
        author = time_search_scope[: time_match.start()].strip()
    elif src_anchor:
        author = meta_line[: src_anchor.start()].strip()
    author = author[:40]
    return meta_line, body, author, time_str, source


_NOISE_TAIL = re.compile(r"(\n\s*(转发|讨论|赞|收藏|展开|网页链接)\s*)+.*$", re.DOTALL)


def _clean_body(body: str) -> str:
    """清理正文尾部交互噪声（转发/讨论/赞/收藏/展开/网页链接 + 数字）。"""
    body = _NOISE_TAIL.sub("", body)
    kept = []
    for ln in body.split("\n"):
        s = ln.strip()
        if s in ("转发", "讨论", "赞", "收藏", "展开", "网页链接"):
            continue
        if re.fullmatch(r"\d+", s):
            continue
        kept.append(ln)
    return _clean_pua("\n".join(kept)).strip()


def _parse_discussion(item, links: List[str] = None) -> Optional[Discussion]:
    """item 可为 dict（结构化）或 str（innerText 回退，兼容旧测试）。"""
    try:
        if isinstance(item, dict):
            links = item.get("links", [])
            author = (item.get("author") or "")[:40]
            time_str, source = _parse_date_source(item.get("date_source", ""))
            content = _clean_body(item.get("content") or "")[:500]
            raw_text = item.get("text", "")
            # 结构化字段缺失时回退 innerText
            if not author or not content:
                _m, body, a2, t2, s2 = _split_meta_line(raw_text)
                author = author or a2
                time_str = time_str or t2
                source = source or s2
                content = content or _clean_body(body)[:500]
        else:
            links = links or []
            _m, body, author, time_str, source = _split_meta_line(item)
            content = _clean_body(body)[:500]

        # 只有显式标注"来自雪球专栏"才是专栏文章
        # 普通讨论空来源会 fallback 到"雪球", 不算专栏
        is_column = (source or "").strip().lower().find("专栏") >= 0

        link = ""
        for href in links:
            if re.match(r"/\d+/\d+$", href):
                link = "https://xueqiu.com" + href
                break

        if content and len(content) > 10:
            return Discussion(
                author=author, content=content, time=time_str,
                link=link, is_column=is_column,
            )
    except Exception:
        pass
    return None


def _parse_news(item, links: List[str] = None) -> Optional[News]:
    try:
        if isinstance(item, dict):
            links = item.get("links", [])
            time_str, source = _parse_date_source(item.get("date_source", ""))
            content_field = item.get("content") or ""
            raw_text = item.get("text", "")
            # 资讯标题常在 content 首行（或 innerText body 首行）
            src = content_field if content_field else raw_text
            body_lines = [ln for ln in src.split("\n") if ln.strip()]
            if content_field:
                title = body_lines[0].strip()[:200] if body_lines else ""
                content = "\n".join(body_lines[1:]).strip() if len(body_lines) > 1 else ""
            else:
                _m, body, _a, t2, s2 = _split_meta_line(raw_text)
                time_str = time_str or t2
                source = source or s2
                bl = [ln for ln in body.split("\n") if ln.strip()]
                title = bl[0].strip()[:200] if bl else raw_text[:80]
                content = "\n".join(bl[1:]).strip() if len(bl) > 1 else ""
            content = _clean_body(content)[:3000]
        else:
            links = links or []
            _m, body, _a, time_str, source = _split_meta_line(item)
            bl = [ln for ln in body.split("\n") if ln.strip()]
            title = bl[0].strip()[:200] if bl else item[:80]
            content = _clean_body("\n".join(bl[1:]))[:3000] if len(bl) > 1 else ""

        if not title:
            return None

        # 若 source 为空，尝试从正文开头提取"来源：XXX"（雪球资讯正文一般这么写）
        if not source and content:
            first_line = content.split('\n')[0].strip()
            m = re.search(r'^来源[：:][ \t]*([^ \t]+)', first_line)
            if m:
                source = m.group(1)
                # 删掉来源行
                content = '\n'.join(content.split('\n')[1:]).strip()

        link = ""
        for href in links:
            if href and not href.startswith("javascript"):
                full = href if href.startswith("http") else "https://xueqiu.com" + href
                if not re.search(r"/S/[A-Z0-9]+$", full):
                    link = full
                    break

        return News(
            title=title, content=content, time=time_str,
            source=source or "新闻", link=link,
        )
    except Exception:
        pass
    return None


def _parse_notice(item, links: List[str] = None) -> Optional[Notice]:
    """公告条目解析。body/content 首行为标题。"""
    try:
        if isinstance(item, dict):
            links = item.get("links", [])
            time_str, _src = _parse_date_source(item.get("date_source", ""))
            src = item.get("content") or item.get("text", "")
        else:
            links = links or []
            _m, src, _a, time_str, _s = _split_meta_line(item)
        body_lines = [ln for ln in (src or "").split("\n") if ln.strip()]
        if not body_lines:
            return None
        title = _clean_pua(body_lines[0].strip())[:100]
        title = title.rstrip().removesuffix("网页链接").rstrip()
        if not title or title in ("转发", "讨论", "赞", "收藏"):
            return None
        link = ""
        for href in links:
            if href and not href.startswith("javascript"):
                link = href if href.startswith("http") else "https://xueqiu.com" + href
                break
        return Notice(title=title, link=link, time=time_str)
    except Exception:
        pass
    return None


def _is_beyond_time_window(time_str: str, days: int) -> bool:
    """DOM 时间字符串是否超出 days 窗口（保守：解析不了返回 False）。"""
    if not time_str or days <= 0:
        return False
    now = datetime.now()
    m = re.match(r"(\d+)天前", time_str)
    if m:
        return int(m.group(1)) > days
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", time_str)
    if m:
        try:
            dt = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            return (now - dt).days > days
        except Exception:
            return False
    # 秒前/分钟前/小时前/昨天/今天 都在窗口内
    return False


# ════════════════════════════════════════════════════════
# nodriver 爬虫主类
# ════════════════════════════════════════════════════════
class XueqiuNodriverCrawler:
    """nodriver 版股票页爬虫，接口对齐 XueqiuCrawler.crawl。"""

    def __init__(self, config: dict = None):
        if uc is None:
            raise ImportError("请安装 nodriver: pip install nodriver")
        config = config or {}
        self.headless = config.get("headless", True)
        self.browser = None
        self.tab = None

    # ── 浏览器管理 ──
    async def _start_browser(self):
        if self.browser is not None:
            return
        cfg = uc.Config(headless=self.headless, sandbox=False)
        self.browser = await uc.start(config=cfg)
        logger.info("nodriver 浏览器已启动")

    async def _close_browser(self):
        if self.browser is None:
            return
        try:
            self.browser.stop()
        except Exception:
            pass
        self.browser = None
        self.tab = None

    async def _warmup(self):
        """访问首页预热会话 — 模拟人类行为降低 WAF 触发。"""
        self.tab = await self.browser.get("https://xueqiu.com")
        await self.tab.sleep(3)
        await self.tab.evaluate("window.scrollBy(0, 300)")
        await self.tab.sleep(1)
        await self.tab.evaluate("window.scrollBy(0, -200)")
        logger.info("会话预热完成")

    async def _navigate(self, url: str, wait_seconds: float = 4):
        self.tab = await self.browser.get(url)
        await self.tab.sleep(wait_seconds)

    async def _page_title(self) -> str:
        try:
            return await self.tab.evaluate("document.title") or ""
        except Exception:
            return ""

    async def _detect_waf(self) -> bool:
        title = await self._page_title()
        for pat in _WAF_TITLE_PATTERNS:
            if pat in (title or ""):
                logger.warning(f"检测到 WAF 页面 (title={title!r})")
                return True
        try:
            content = await self.tab.evaluate(
                "document.documentElement.outerHTML.slice(0, 5000)"
            )
        except Exception:
            content = ""
        if has_waf_marker(content or ""):
            logger.warning("检测到 WAF 标记 (waf.PAGE_MARKERS)")
            return True
        return False

    async def _wait_for_selector(self, selector: str, timeout_s: float = 8.0) -> bool:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            try:
                cnt = await self.tab.evaluate(
                    f"document.querySelectorAll('{selector}').length"
                )
                if cnt and cnt > 0:
                    return True
            except Exception:
                pass
            await self.tab.sleep(0.5)
        return False

    async def _switch_tab(self, tab_name: str) -> bool:
        """点击名为 tab_name 的 tab（讨论/资讯/公告）。"""
        try:
            clicked = await self.tab.evaluate(
                """(function(name){
                    var all = document.querySelectorAll('a, .nav-tabs a, .tab, li, span');
                    for (var i=0;i<all.length;i++){
                        var t = (all[i].innerText||'').trim();
                        if (t === name){ all[i].click(); return true; }
                    }
                    return false;
                })('""" + tab_name + "')"
            )
            if clicked:
                await self.tab.sleep(random.uniform(2, 4))
                await self._wait_for_selector(".timeline__item", timeout_s=6)
                return True
        except Exception as e:
            logger.debug(f"切换 tab '{tab_name}' 失败: {e}")
        return False

    async def _extract_timeline(self, max_items: int = 200) -> List[dict]:
        """从 DOM 结构化提取每个 .timeline__item 的字段。

        雪球 timeline DOM：
          .user-name        → 作者（精确，无数字歧义）
          .date-and-source  → '9秒前· 来自Android'
          .timeline__item__content / .content--description → 正文
          首个 a[href] → 作者主页；/\\d+/\\d+ → 帖子链接
        回退：若子元素缺失，用 innerText 堆到 raw_text 供解析器兼容。
        """
        try:
            data = await self.tab.evaluate(
                """(function(limit){
                    var out = [];
                    var items = document.querySelectorAll('.timeline__item');
                    for (var i=0;i<items.length && i<limit;i++){
                        var el = items[i];
                        function txt(sel){var e=el.querySelector(sel);return e?(e.innerText||'').trim():'';}
                        var author = txt('.user-name');
                        var dateSrc = txt('.date-and-source');
                        var content = txt('.timeline__item__content') || txt('.content--description');
                        var links = [];
                        var as = el.querySelectorAll('a');
                        for (var j=0;j<as.length;j++){
                            var h = as[j].getAttribute('href');
                            if (h) links.push(h);
                        }
                        out.push({
                            author: author,
                            date_source: dateSrc,
                            content: content,
                            text: (el.innerText||'').trim(),
                            links: links
                        });
                    }
                    return JSON.stringify(out);
                })(""" + str(max_items) + ")"
            )
            if isinstance(data, str):
                import json as _json
                return _json.loads(data)
            return data or []
        except Exception as e:
            logger.debug(f"提取 timeline 失败: {e}")
            return []

    async def _paginate_and_collect(
        self, max_pages: int, days: int, seen: set
    ) -> List[dict]:
        """翻页收集 timeline 原始条目 {text, links}。"""
        collected = []
        stale_pages = 0
        for page_num in range(1, max_pages + 1):
            try:
                await self.tab.evaluate(
                    "window.scrollTo(0, document.body.scrollHeight)"
                )
                await self.tab.sleep(random.uniform(0.8, 1.5))
                items = await self._extract_timeline()
                new_this_page = 0
                beyond_window = False
                for it in items:
                    sig = (it.get("text", "") or "")[:50]
                    if sig and sig not in seen:
                        seen.add(sig)
                        collected.append(it)
                        new_this_page += 1
                        # 时间窗早停：讨论页按时间倒序，遇到超窗帖子即标记
                        ts, _ = _parse_date_source(it.get("date_source", ""))
                        if _is_beyond_time_window(ts, days):
                            beyond_window = True
                logger.info(
                    f"[nodriver DOM] 分页[{page_num}] 本页新增:{new_this_page} 累计:{len(collected)}"
                )
                if beyond_window:
                    logger.info(f"[nodriver DOM] 达到 {days} 天时间窗，停止翻页")
                    break
                if new_this_page == 0:
                    stale_pages += 1
                else:
                    stale_pages = 0
                if stale_pages >= 3:
                    break
                clicked = await self.tab.evaluate(
                    """(function(){
                        var all = document.querySelectorAll('a, button, div, span');
                        for (var i=0;i<all.length;i++){
                            if ((all[i].innerText||'').trim() === '下一页'){
                                all[i].click(); return true;
                            }
                        }
                        return false;
                    })()"""
                )
                if clicked:
                    await self.tab.sleep(random.uniform(1.5, 3))
                else:
                    break
            except Exception as e:
                logger.debug(f"翻页异常: {e}")
                break
        return collected

    # ── 主入口 ──
    def crawl(
        self,
        symbol: str,
        max_pages: int = 10,
        max_articles: int = 200,
        days: int = 2,
    ) -> CrawlResult:
        """同步入口，内部跑 async。接口对齐 XueqiuCrawler.crawl。"""
        return asyncio.run(
            self._crawl_async(symbol, max_pages, max_articles, days)
        )

    async def _crawl_async(
        self, symbol: str, max_pages: int, max_articles: int, days: int
    ) -> CrawlResult:
        result = CrawlResult(symbol=symbol)
        try:
            await self._start_browser()
            await self._warmup()

            url = _xueqiu_url_for_symbol(symbol)
            logger.info(f"nodriver 访问股票页: {url}")
            await self._navigate(url, wait_seconds=random.uniform(4, 6))

            if await self._detect_waf():
                raise WafDetectedError(f"WAF at stock page: {symbol}")

            # 股票名 / 价格
            try:
                result.name = (
                    await self.tab.evaluate(
                        "(document.querySelector('.stock-name')||{}).innerText || ''"
                    )
                ) or ""
                result.price = (
                    await self.tab.evaluate(
                        "(document.querySelector('[class*=\"stock-current\"]')||{}).innerText || ''"
                    )
                ) or ""
            except Exception:
                pass

            seen: set = set()

            # ── 讨论 tab ──
            if await self._switch_tab("讨论"):
                raw = await self._paginate_and_collect(max_pages, days, seen)
                for it in raw:
                    d = _parse_discussion(it)
                    if not d:
                        continue
                    if d.is_column:
                        result.articles.append(
                            Article(
                                title=d.content[:50], author=d.author,
                                content=d.content[:5000], time=d.time,
                                link=d.link, is_column=True,
                            )
                        )
                    else:
                        result.discussions.append(d)

            # ── 资讯 tab ──
            if await self._switch_tab("资讯"):
                seen_news: set = set()
                raw = await self._paginate_and_collect(max_pages, days, seen_news)
                for it in raw:
                    n = _parse_news(it)
                    if n:
                        result.news.append(n)

            # ── 公告 tab ──
            if await self._switch_tab("公告"):
                seen_nt: set = set()
                raw = await self._paginate_and_collect(min(max_pages, 3), days, seen_nt)
                for it in raw:
                    nt = _parse_notice(it)
                    if nt and nt.title:
                        result.notices.append(nt)

            logger.info(
                f"nodriver 完成: {len(result.discussions)}讨论 "
                f"{len(result.news)}资讯 {len(result.notices)}公告 "
                f"{len(result.articles)}专栏"
            )
            return result
        finally:
            await self._close_browser()

    def close(self):
        """兼容 XueqiuCrawler.close() 接口（同步 no-op，async 已在 finally 关闭）。"""
        pass


def _xueqiu_url_for_symbol(symbol: str) -> str:
    """symbol → 雪球股票页 URL。"""
    return f"https://xueqiu.com/S/{symbol}"
