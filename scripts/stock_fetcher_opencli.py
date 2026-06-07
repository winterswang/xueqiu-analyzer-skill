#!/usr/bin/env python3
"""
OpenCLI-based stock data fetcher for xueqiu-analyzer.

Uses opencli Chrome extension to fetch stock discussions and quotes
with zero WAF issues. Falls back to Playwright crawler when unavailable.

Requirements:
    - opencli installed and Chrome extension connected
"""

import json
import logging
import re
import shutil
import subprocess
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import List, Optional

logger = logging.getLogger(__name__)

# Reuse the same dataclasses as stock_crawler_v2 for compatibility
@dataclass
class Discussion:
    author: str
    time: str
    content: str
    link: str = ""

@dataclass
class Article:
    title: str
    author: str
    time: str
    content: str
    link: str
    article_id: str = ""

@dataclass
class News:
    title: str
    time: str
    summary: str = ""
    link: str = ""
    source: str = ""

@dataclass
class Notice:
    title: str
    time: str
    link: str = ""
    content: str = ""
    pdf_link: str = ""

@dataclass
class StockInfo:
    symbol: str
    name: str = ""
    price: str = ""
    change: str = ""
    discussions: List[Discussion] = field(default_factory=list)
    news: List[News] = field(default_factory=list)
    notices: List[Notice] = field(default_factory=list)
    articles: List[Article] = field(default_factory=list)
    financial_data: dict = field(default_factory=dict)


def is_available() -> bool:
    """Check if opencli is installed and Chrome extension connected."""
    if not shutil.which("opencli"):
        return False
    try:
        result = subprocess.run(
            ["opencli", "doctor"],
            capture_output=True, text=True, timeout=10,
        )
        return "[OK] Extension: connected" in result.stdout
    except Exception:
        return False


def _run(*args: str, timeout: int = 30) -> subprocess.CompletedProcess:
    """Run opencli command."""
    cmd = ["opencli"] + list(args)
    logger.debug(f"opencli: {' '.join(cmd)}")
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _clean_json(stdout: str) -> str:
    """Strip opencli noise (update notices) from JSON output."""
    lines = stdout.splitlines()
    cleaned = []
    skip = False
    for line in lines:
        if "Update available" in line:
            skip = True
            continue
        if skip and line.startswith("  Run:"):
            skip = False
            continue
        if not skip:
            cleaned.append(line)
    return "\n".join(cleaned)


def fetch_stock_quote(symbol: str) -> dict:
    """Fetch stock quote via opencli xueqiu stock."""
    result = _run("xueqiu", "stock", symbol, "-f", "json", timeout=20)
    if result.returncode != 0:
        logger.error(f"stock quote failed: {result.stderr[:200]}")
        return {}
    try:
        data = json.loads(_clean_json(result.stdout))
        if isinstance(data, list) and data:
            data = data[0]
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def fetch_discussions(symbol: str, limit: int = 20) -> List[dict]:
    """Fetch stock discussions via opencli xueqiu comments."""
    result = _run("xueqiu", "comments", symbol, "--limit", str(limit), "-f", "json", timeout=30)
    if result.returncode != 0:
        logger.error(f"comments failed: {result.stderr[:200]}")
        return []
    try:
        data = json.loads(_clean_json(result.stdout))
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


class OpencliStockFetcher:
    """Fetch xueqiu stock data via opencli Chrome extension."""

    def __init__(self):
        pass

    def fetch(self, symbol: str, max_discussions: int = 20,
              max_news: int = 0, max_articles: int = 0) -> StockInfo:
        """Fetch stock data. Returns StockInfo with same interface as crawler.

        Note: max_news and max_articles are accepted for API compatibility
        but currently only discussions are fetched via opencli.
        """
        stock_info = StockInfo(symbol=symbol)

        # 1. Fetch stock quote
        quote = fetch_stock_quote(symbol)
        stock_info.name = quote.get("name", "")
        stock_info.price = str(quote.get("current", ""))
        stock_info.change = str(quote.get("percent", ""))

        # 2. Fetch discussions
        discussions_raw = fetch_discussions(symbol, limit=max_discussions)
        for d in discussions_raw:
            # Extract text, skip @-reply noise
            text = d.get("text", "").strip()
            # Skip pure replies (start with 回复@)
            if text.startswith("回复@"):
                # Try to extract the actual content after //@ patterns
                parts = re.split(r"//\s*@", text)
                text = parts[0].strip()
                if text.startswith("回复@"):
                    text = text.split(":", 1)[-1].strip() if ":" in text else ""

            if len(text) > 10:  # meaningful content
                stock_info.discussions.append(Discussion(
                    author=d.get("author", "")[:30],
                    time=d.get("created_at", ""),
                    content=text[:500],
                    link=d.get("url", ""),
                ))

        logger.info(f"opencli: fetched {len(stock_info.discussions)} discussions for {symbol}")
        return stock_info

    def to_dict(self, stock_info: StockInfo) -> dict:
        """Convert StockInfo to dict (same format as crawler.to_dict)."""
        return {
            'symbol': stock_info.symbol,
            'name': stock_info.name,
            'price': stock_info.price,
            'discussions': [asdict(d) for d in stock_info.discussions],
            'articles': [asdict(a) for a in stock_info.articles],
            'news': [asdict(n) for n in stock_info.news],
            'notices': [asdict(n) for n in stock_info.notices],
            'financial_data': stock_info.financial_data,
            'crawl_time': datetime.now().isoformat(),
            'source': 'opencli',
        }
