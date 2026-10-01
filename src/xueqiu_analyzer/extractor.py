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

# 防御性加载 .env（模块被独立 import 时也能拿到环境变量）
_dotenv_path = Path(__file__).resolve().parent.parent.parent / '.env'
try:
    from dotenv import load_dotenv
    if _dotenv_path.exists():
        load_dotenv(_dotenv_path, override=False)
except ImportError:
    # 不能静默：python-dotenv 缺失 → .env 不会被加载 → key 恒为空 →
    # 请求带着 `Authorization: Bearer ` 发出去，换回一个语焉不详的 401。
    # 2026-06-08 正是这个事故（见 DAILY_LOG.md）。
    logger.warning(
        "python-dotenv 未安装，%s 不会被加载，只能依赖已导出的环境变量。"
        "需要 .env 生效请执行 pip install python-dotenv。", _dotenv_path,
    )

# DeepSeek API 配置
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-v4-flash"


class MissingCredentialError(RuntimeError):
    """凭证未配置 —— 与「API 调用失败」区分开。

    以前 key 为空照样发请求，拿回 401，日志只留下「DeepSeek API 调用失败:
    HTTP Error 401」—— 看不出是配置问题，只会往网络或额度的方向排查。
    """


def _deepseek_api_key() -> str:
    """调用时读取 DeepSeek API key，缺失则抛错。

    刻意不在导入时缓存成模块常量：那样取值时机取决于 import 顺序与 .env
    加载先后，曾出现过「环境变量明明设了却读到空」。
    """
    key = (os.environ.get("DEEPSEEK_API_KEY") or "").strip()
    if not key:
        raise MissingCredentialError(
            "DEEPSEEK_API_KEY 未配置。\n"
            f"  读取顺序: 环境变量 DEEPSEEK_API_KEY → {_dotenv_path}\n"
            "  修复: 在 .env 写入 DEEPSEEK_API_KEY=sk-...，或导出同名环境变量。\n"
            "  注意: .env 存在但未生效时，检查 python-dotenv 是否已安装。"
        )
    return key

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

EXTRACT_PROMPT = """你是一个专业的文章正文提取助手。请从网页文本内容中提取文章信息。

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
- 输入已是提取后的纯文本内容，无需处理 HTML 标签

请提取以下内容：

"""

EXTRACT_USER_PROMPT = """## 待提取的文章文本

（见下方文本）

"""


# ── JSON 截断修复 ──────────────────────────────────────────────────────────

def _repair_truncated_json(s: str) -> str:
    """Attempt to repair a truncated JSON string by closing open braces/quotes."""
    if not s:
        return s
    s = s.rstrip()
    # Count unbalanced braces
    open_braces = s.count('{') - s.count('}')
    open_brackets = s.count('[') - s.count(']')
    # Close trailing quote if inside a string value
    in_string = False
    escape = False
    for c in s:
        if escape:
            escape = False
            continue
        if c == '\\':
            escape = True
        elif c == '"':
            in_string = not in_string
    if in_string:
        s += '"'
    # Close braces
    if open_braces > 0 or open_brackets > 0:
        # Try to find the last incomplete value and trim it
        last_comma = s.rfind(',')
        last_colon = s.rfind(':')
        if last_colon > last_comma and last_colon > 0:
            # Remove incomplete value (text after last colon that isn't a quote or number)
            s = s[:last_colon] + ': ""'
        s += ']' * max(0, open_brackets) + '}' * max(0, open_braces)
    return s


# ── DeepSeek API 调用 ────────────────────────────────────────────────────────

def call_deepseek_extract(text_content: str, url: str) -> ArticleContent:
    """调用 DeepSeek API 提取文章内容（输入为纯文本，非 HTML）"""
    user_content = EXTRACT_USER_PROMPT + f"\n## 原文链接\n{url}\n\n## 文本内容\n{text_content[:15000]}"

    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": EXTRACT_PROMPT},
            {"role": "user", "content": user_content}
        ],
        "max_tokens": 8000,
        "temperature": 0.1,
    }

    # 提前校验凭证：缺失时抛出可操作的错误，而不是发一个 Bearer 空的请求换 401。
    # 刻意放在 try 之外 —— 这是配置问题，不该被「调用失败」的兜底吞掉。
    api_key = _deepseek_api_key()

    req = urllib.request.Request(
        f"{DEEPSEEK_BASE_URL}/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
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

            try:
                data = json.loads(json_str)
            except json.JSONDecodeError:
                # JSON truncated — try to repair by completing braces
                repaired = _repair_truncated_json(json_str)
                if repaired:
                    data = json.loads(repaired)
                else:
                    raise
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
    """清理无用的 HTML 标签，返回纯文本"""
    import re
    # 移除 script, style, nav, footer, aside 等标签及其内容
    text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<nav[^>]*>.*?</nav>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<footer[^>]*>.*?</footer>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<aside[^>]*>.*?</aside>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<header[^>]*>.*?</header>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<div class="[^"]*(?:comment|related|sidebar|ad|advertisement)[^"]*"[^>]*>.*?</div>',
                  '', text, flags=re.DOTALL | re.IGNORECASE)
    # 移除 HTML 标签转为纯文本
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


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

    def extract(self, url: str, raw_text: str = None, raw_html: str = None,
                fallback_selector: str = None) -> ArticleContent:
        """
        提取文章正文

        Args:
            url: 文章详情页 URL
            raw_text: 可选，预提取的纯文本内容（优先使用，内存占用远小于 raw_html）
            raw_html: 可选，预渲染的页面 HTML（向后兼容，会转为纯文本）
            fallback_selector: 可选的 fallback CSS selector

        Returns:
            ArticleContent: 提取结果
        """
        logger.info(f"使用 LLM 提取文章: {url}")

        try:
            # Step 1: 获取文本内容
            if raw_text:
                text = raw_text
            elif raw_html:
                text = _clean_html(raw_html)
            else:
                html = fetch_page_html(url, cookies=self.cookies)
                text = _clean_html(html)

            if not text or len(text) < 50:
                logger.warning(f"页面文本为空或太短: {url}")
                return self._fallback(url, fallback_selector)

            # Step 2: DeepSeek 提取
            result = call_deepseek_extract(text, url)

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
