"""OpenCLI-based fetcher for xueqiu-analyzer.

Routes xueqiu data requests through opencli Chrome extension (zero-WAF),
falling back silently when the extension is unavailable.

Architecture:
    Each fetch_* function returns an empty result on failure — callers
    should check and fall back to their own Tier 2/3 implementations.
"""

from __future__ import annotations

import os
import io
import json
import logging
import re
import shutil
import subprocess
from typing import Any

from .waf import classify_failure

logger = logging.getLogger(__name__)

# ── 源级失败记录 ──────────────────────────────────────────
# 任一信息源抓取失败就追加一行 JSON，让『哪个源挂了』可被 health_check 与日报读到，
# 而不是静默返回空列表。路径优先取环境变量 XQ_SOURCE_FAIL_LOG，
# 否则落到 <cwd>/logs/source_failures.jsonl（monitor 的 cron 以项目根为 cwd）。
FAIL_LOG = os.environ.get('XQ_SOURCE_FAIL_LOG') or os.path.join(os.getcwd(), 'logs', 'source_failures.jsonl')

# 跨天时旧日志归档到 <FAIL_LOG 同级的 logs>/source_failures/YYYY-MM-DD.jsonl，保留天数见下。
FAIL_ARCHIVE_KEEP_DAYS = 30


def _rotate_fail_log(path=None, keep_days=None):
    """跨天时归档旧失败日志并清理过期归档，返回归档路径或 None。

    只在『文件最后写入日 < 今天』时轮转 —— 同一天内多次调用不动文件，
    所以读取方（monitor 的 health_check / cli）仍只需读固定路径，
    就能拿到当天的全部记录，不会因为轮转丢掉今天的早期失败。
    """
    from datetime import date, timedelta
    p = path or FAIL_LOG
    try:
        if not os.path.exists(p) or os.path.getsize(p) == 0:
            return None
        day = date.fromtimestamp(os.path.getmtime(p))
        if day >= date.today():
            return None

        archive_dir = os.path.join(os.path.dirname(p), 'source_failures')
        os.makedirs(archive_dir, exist_ok=True)
        dest = os.path.join(archive_dir, '%s.jsonl' % day.isoformat())
        if os.path.exists(dest):
            # 同一天二次归档（理论上不该发生）：追加而非覆盖
            with io.open(p, 'r', encoding='utf-8') as src, io.open(dest, 'a', encoding='utf-8') as dst:
                dst.write(src.read())
            os.remove(p)
        else:
            os.replace(p, dest)

        keep = FAIL_ARCHIVE_KEEP_DAYS if keep_days is None else keep_days
        cutoff = date.today() - timedelta(days=keep)
        for name in os.listdir(archive_dir):
            if not name.endswith('.jsonl'):
                continue
            try:
                if date.fromisoformat(name[:-len('.jsonl')]) < cutoff:
                    os.remove(os.path.join(archive_dir, name))
            except ValueError:
                continue
        return dest
    except Exception:
        return None

def record_source_failure(source, target, rc, err):
    # 把一次源抓取失败落盘；写失败也不影响主流程。
    # 归类用 waf.classify_failure（唯一实现）—— 风控关键词表在 xueqiu_analyzer.waf。
    from datetime import datetime
    first_line = (err or '').strip().splitlines()[0][:200] if (err or '').strip() else ''
    rec = {'ts': datetime.now().isoformat(timespec='seconds'), 'source': source,
           'target': str(target), 'rc': rc, 'reason': classify_failure(err), 'error': first_line}
    try:
        d = os.path.dirname(FAIL_LOG)
        if d:
            os.makedirs(d, exist_ok=True)
        _rotate_fail_log(FAIL_LOG)
        with io.open(FAIL_LOG, 'a', encoding='utf-8') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + chr(10))
    except Exception:
        pass
    return rec


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
            _err = result.stderr or ""
            _quiet = ("EMPTY_RESULT" in _err) or ("no data" in _err)
            (logger.debug if _quiet else logger.warning)(
                f"opencli stock {symbol} 失败(rc={result.returncode}): {_err.strip()[:220]}")
            if not _quiet:
                record_source_failure('stock', symbol, result.returncode, _err)
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
            _err = result.stderr or ""
            _quiet = ("EMPTY_RESULT" in _err) or ("no data" in _err)
            (logger.debug if _quiet else logger.warning)(
                f"opencli comments {symbol} 失败(rc={result.returncode}): {_err.strip()[:220]}")
            if not _quiet:
                record_source_failure('comments', symbol, result.returncode, _err)
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
            _err = result.stderr or ""
            _quiet = ("EMPTY_RESULT" in _err) or ("no data" in _err)
            (logger.debug if _quiet else logger.warning)(
                f"opencli news {symbol} 失败(rc={result.returncode}): {_err.strip()[:220]}")
            if not _quiet:
                record_source_failure('news', symbol, result.returncode, _err)
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
            _err = result.stderr or ""
            _quiet = ("EMPTY_RESULT" in _err) or ("no data" in _err)
            (logger.debug if _quiet else logger.warning)(
                f"opencli replies {post_url} 失败(rc={result.returncode}): {_err.strip()[:220]}")
            if not _quiet:
                record_source_failure('replies', post_url, result.returncode, _err)
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
            _err = result.stderr or ""
            _quiet = ("EMPTY_RESULT" in _err) or ("no data" in _err)
            (logger.debug if _quiet else logger.warning)(
                f"opencli stock-notices {symbol} 失败(rc={result.returncode}): {_err.strip()[:220]}")
            if not _quiet:
                record_source_failure('stock-notices', symbol, result.returncode, _err)
            return []
        data = json.loads(_clean_json(result.stdout))
        return data if isinstance(data, list) else []
    except Exception as e:
        logger.debug(f"opencli stock-notices {symbol} failed: {e}")
        return []
