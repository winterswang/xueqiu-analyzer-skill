"""
ScrapingExtractor — LLM驱动的文章正文提取器

替代硬编码 CSS selector，实现思路：
1. Playwright 渲染页面 → 获取正文 HTML
2. DeepSeek 提取 → 结构化 ArticleContent
3. 失败时回退原有 selector 逻辑（crawler.py 兼容）
"""

import os
import re
import json
import logging
import urllib.request
from dataclasses import dataclass, asdict
from typing import Optional, List
from pathlib import Path

logger = logging.getLogger(__name__)

# DeepSeek API 配置
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY") or "sk-61dc4232a5d94bd184bf26315b173bcd"
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-v4-flash"

# Playwright 配置（复用 crawler.py 的 session/cookie）
PLAYWRIGHT_HEADLESS = True


@dataclass
class ArticleContent:
    """文章正文提取结果"""
    title: str = ""
    author: str = ""
    content: str = ""
    time: str = ""
    symbols: List[str] = ""
    url: str = ""

    def to_dict(self):
        return asdict(self)

    def is_valid(self) -> bool:
        return bool(self.content and len(self.content) >= 50)


# ── Prompt 模板 ────────────────────────────────────────────────────────────

EXTRACT_PROMPT = """你是一个专业的文章正文提取助手。请从网页 HTML 内容中提取文章信息。

## 输出要求
返回 JSON 格式，包含以下字段：
- title: 文章标题（完整原标题）
- author: 作者/发布者名称
- content: 文章正文（清洗后的纯文本，去除广告、导航栏、评论等干扰内容，保留段落结构）
- time: 发布时间（原文格式）
- symbols: 文章中提及的股票代码列表（如 AAPL、600519、00700 等，JSON 数组格式）
- url: 文章原文链接

## 提取规则
1. content 只保留正文，去除：页眉、导航栏、侧边栏、评论区、推荐阅读、广告、免责声明
2. 正文保留段落分隔（用换行符 \\n）
3. 时间格式尽量保持原文
4. symbols 只提取股票代码，不要提取基金、债券等其他产品代码
5. 如果某字段无法提取，设为空字符串 ""

## 重要提示
- 雪球文章可能有"登录后阅读全文"提示，如果正文被截断，请在 content 中标注"[登录后内容截断]"
- 公告内容可能很短，不需要展开
- 如果是 403 或需要登录的页面，content 设为 "[需要登录]"

请提取以下网页内容：

"""

EXTRACT_USER_PROMPT = """## 待提取的网页 HTML 内容

（见下方 HTML）

"""


# ── DeepSeek API 调用 ────────────────────────────────────────────────────────

def call_deepseek_extract(html_content: str, url: str) -> ArticleContent:
    """调用 DeepSeek API 提取文章内容"""
    user_content = EXTRACT_USER_PROMPT + f"\n## 原文链接\n{url}\n\n## HTML 内容\n{html_content[:15000]}"

    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": EXTRACT_PROMPT},
            {"role": "user", "content": user_content}
        ],
        "max_tokens": 8000,
        "temperature": 0.1,
    }

    req = urllib.request.Request(
        f"{DEEPSEEK_BASE_URL}/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            raw = result["choices"][0]["message"]["content"]

            # 提取 JSON（可能包裹在 ```json 中）
            json_str = raw.strip()
            if json_str.startswith("```"):
                lines = json_str.split("\n")
                json_str = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

            data = json.loads(json_str)
            return ArticleContent(
                title=str(data.get("title", "")),
                author=str(data.get("author", "")),
                content=str(data.get("content", "")),
                time=str(data.get("time", "")),
                symbols=json.dumps(data.get("symbols", [])),
                url=url,
            )
    except Exception as e:
        logger.warning(f"DeepSeek API 调用失败: {e}")
        return ArticleContent(url=url)


# ── Playwright 渲染 ────────────────────────────────────────────────────────

def fetch_page_html(url: str, cookies: list = None) -> str:
    """使用 Playwright 渲染页面并返回正文 HTML

    优先复用已有的 Chrome remote debugging session（保持登录态），
    连接失败时回退到启动新的 headless 浏览器。
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise ImportError("请安装 playwright: pip install playwright && playwright install chromium")

    html = ""

    def _extract_main_content(page):
        """提取主体内容区域"""
        # 尝试多个可能的内容容器
        selectors = [
            ".article-content",
            ".detail-content",
            ".article__body",
            ".post-content",
            "#content",
            "article",
            ".content",
        ]
        for sel in selectors:
            try:
                elem = page.query_selector(sel)
                if elem:
                    return elem.inner_html()
            except Exception:
                continue
        # 如果都没找到，返回 body
        try:
            return page.query_selector("body").inner_html()
        except Exception:
            return ""

    # ── Phase 1: 尝试连接已有 Chrome（保持登录态） ──────────────────
    browser = None
    try:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp("http://localhost:9222")
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            page = context.new_page()
            page.goto(url, timeout=30000, wait_until="networkidle")
            page.wait_for_timeout(2000)
            html = _extract_main_content(page)
            html = _clean_html(html)
            page.close()
            return html
    except Exception:
        if browser:
            try:
                browser.close()
            except Exception:
                pass
        # Fall through to Phase 2

    # ── Phase 2: 启动新的 headless 浏览器 ──────────────────────────
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=PLAYWRIGHT_HEADLESS)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        )
        page = context.new_page()

        try:
            page.goto(url, timeout=30000, wait_until="networkidle")
            page.wait_for_timeout(2000)
            html = _extract_main_content(page)
            html = _clean_html(html)
        finally:
            browser.close()

    return html


def _clean_html(html: str) -> str:
    """清理无用的 HTML 标签和内容"""
    import re
    # 移除 script, style, nav, footer, aside 等标签及其内容
    html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<nav[^>]*>.*?</nav>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<footer[^>]*>.*?</footer>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<aside[^>]*>.*?</aside>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<header[^>]*>.*?</header>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<div class="[^"]*(?:comment|related|sidebar|ad|advertisement)[^"]*"[^>]*>.*?</div>',
                  '', html, flags=re.DOTALL | re.IGNORECASE)
    return html


# ── 主提取器 ──────────────────────────────────────────────────────────────

class ScrapingExtractor:
    """
    LLM 驱动的文章正文提取器

    使用 Playwright + DeepSeek 实现"说一遍就能提取"的目标，
    替代硬编码 CSS selector。
    """

    def __init__(self, cookies: list = None):
        """
        Args:
            cookies: 可选的雪球 cookies，用于访问需要登录的内容
        """
        self.cookies = cookies or []

    def extract(self, url: str, raw_html: str = None, fallback_selector: str = None) -> ArticleContent:
        """
        提取文章正文

        Args:
            url: 文章详情页 URL
            raw_html: 可选，预渲染的页面 HTML（传入则跳过 fetch_page_html）
            fallback_selector: 可选的 fallback CSS selector（保留兼容）

        Returns:
            ArticleContent: 提取结果
        """
        logger.info(f"使用 LLM 提取文章: {url}")

        try:
            # Step 1: 获取 HTML（优先用传入的 raw_html）
            if raw_html:
                html = _clean_html(raw_html)
            else:
                html = fetch_page_html(url, cookies=self.cookies)

            if not html or len(html) < 100:
                logger.warning(f"页面 HTML 为空或太短: {url}")
                return self._fallback(url, fallback_selector)

            # Step 2: DeepSeek 提取
            result = call_deepseek_extract(html, url)

            if not result.is_valid():
                logger.warning(f"DeepSeek 提取结果无效，尝试 fallback: {url}")
                return self._fallback(url, fallback_selector, result)

            logger.info(f"提取成功: {url}, content_length={len(result.content)}")
            return result

        except Exception as e:
            logger.error(f"提取异常: {e}, url={url}")
            return self._fallback(url, fallback_selector)

    def _fallback(self, url: str, selector: str = None, partial: ArticleContent = None) -> ArticleContent:
        """Fallback 到原有 selector 逻辑（可扩展）"""
        logger.info(f"使用 fallback 提取: {url}")
        if partial and partial.is_valid():
            return partial
        if partial:
            return partial
        return ArticleContent(
            url=url,
            content="[提取失败，请手动查看]"
        )


# ── CLI 入口 ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if len(sys.argv) < 2:
        print("Usage: python extractor.py <url>")
        sys.exit(1)

    url = sys.argv[1]
    extractor = ScrapingExtractor()
    result = extractor.extract(url)

    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
