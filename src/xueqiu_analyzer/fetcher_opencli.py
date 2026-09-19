"""OpenCLI-based fetcher for xueqiu-analyzer.

Routes xueqiu data requests through opencli Chrome extension (zero-WAF),
falling back silently when the extension is unavailable.

Architecture:
    Each fetch_* function returns an empty result on failure — callers
    should check and fall back to their own Tier 2/3 implementations.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
from typing import Any

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════
# Availability check (call once at init)
# ════════════════════════════════════════════════════════

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


# ════════════════════════════════════════════════════════
# Low-level helpers
# ════════════════════════════════════════════════════════

def _run(*args: str, timeout: int = 30) -> subprocess.CompletedProcess:
    """Run an opencli command."""
    cmd = ["opencli"] + list(args)
    logger.debug(f"opencli: {' '.join(cmd)}")
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _clean_json(stdout: str) -> str:
    """Strip opencli update-available noise from JSON output."""
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


def _to_xueqiu_symbol(code: str) -> str:
    """Convert watchlist format (9992.HK, PDD.US, 300750.SZ) to xueqiu format (09992, PDD, SZ300750)."""
    if code.endswith('.SH'):
        return 'SH' + code[:-3]
    if code.endswith('.SZ'):
        return 'SZ' + code[:-3]
    if code.endswith('.HK'):
        return code[:-3].zfill(5)
    if code.endswith('.US'):
        return code[:-3]
    return code


# ════════════════════════════════════════════════════════
# Public API — each returns []/{} on failure
# ════════════════════════════════════════════════════════

def fetch_stock_quote(code: str) -> dict:
    """Fetch stock quote via opencli xueqiu stock."""
    symbol = _to_xueqiu_symbol(code)
    try:
        result = _run("xueqiu", "stock", symbol, "-f", "json", timeout=20)
        if result.returncode != 0:
            logger.debug(f"opencli stock {symbol}: {result.stderr[:200]}")
            return {}
        data = json.loads(_clean_json(result.stdout))
        if isinstance(data, list) and data:
            data = data[0]
        return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.debug(f"opencli stock {symbol} failed: {e}")
        return {}


def fetch_discussions(code: str, limit: int = 100) -> list[dict]:
    """Fetch stock discussions via opencli xueqiu comments.

    Returns list of dicts matching the opencli output format:
        {id, author, text, likes, replies, retweets, created_at, url}
    """
    symbol = _to_xueqiu_symbol(code)
    try:
        result = _run("xueqiu", "comments", symbol, "--limit", str(limit), "-f", "json", timeout=60)
        if result.returncode != 0:
            logger.debug(f"opencli comments {symbol}: {result.stderr[:200]}")
            return []
        data = json.loads(_clean_json(result.stdout))
        return data if isinstance(data, list) else []
    except Exception as e:
        logger.debug(f"opencli comments {symbol} failed: {e}")
        return []


def fetch_news(code: str, limit: int = 30) -> list[dict]:
    """Fetch stock news feed via opencli xueqiu news (statuses/stock_timeline.json).

    2026-09-18: the 资讯 tab's real API (captured live, verified without the
    md5__ tracking param). Until now news was only reachable via the
    Playwright DOM path, which the opencli fast path skips — the fast path
    has been silently news-less since it shipped.

    Returns list of dicts: {id, title, text, source, link, created_at}
    (empty list on failure, same contract as the other fetch_* here).
    """
    symbol = _to_xueqiu_symbol(code)
    try:
        result = _run("xueqiu", "news", symbol, "--limit", str(limit), "-f", "json", timeout=60)
        if result.returncode != 0:
            logger.debug(f"opencli news {symbol}: {result.stderr[:200]}")
            return []
        data = json.loads(_clean_json(result.stdout))
        return data if isinstance(data, list) else []
    except Exception as e:
        logger.debug(f"opencli news {symbol} failed: {e}")
        return []


def fetch_replies(post_url: str, limit: int = 20) -> list[dict]:
    """Fetch the reply thread under ONE post via opencli xueqiu replies
    (statuses/comments.json — verified 2026-09-18).

    post_url: the post URL as stored in crawl_snapshots posts_data
    (https://xueqiu.com/<uid>/<status_id>); the adapter extracts the id.

    Returns list of dicts: {id, author, text, likes, created_at, reply_to}
    (empty list on failure / no replies).
    """
    try:
        result = _run("xueqiu", "replies", post_url, "--limit", str(limit), "-f", "json", timeout=90)
        if result.returncode != 0:
            logger.debug(f"opencli replies {post_url}: {result.stderr[:200]}")
            return []
        data = json.loads(_clean_json(result.stdout))
        return data if isinstance(data, list) else []
    except Exception as e:
        logger.debug(f"opencli replies {post_url} failed: {e}")
        return []


def fetch_notices(code: str, limit: int = 50) -> list[dict]:
    """Fetch stock notices via opencli xueqiu stock-notices.

    Returns list of dicts: {title, type, created_at, url}
    """
    symbol = _to_xueqiu_symbol(code)
    try:
        result = _run("xueqiu", "stock-notices", symbol, "--limit", str(limit), "-f", "json", timeout=60)
        if result.returncode != 0:
            logger.debug(f"opencli stock-notices {symbol}: {result.stderr[:200]}")
            return []
        data = json.loads(_clean_json(result.stdout))
        return data if isinstance(data, list) else []
    except Exception as e:
        logger.debug(f"opencli stock-notices {symbol} failed: {e}")
        return []
