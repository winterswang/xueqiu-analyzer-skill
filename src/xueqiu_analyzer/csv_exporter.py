"""
xueqiu-analyzer V3 — CSV 导出模块

将爬取的原始数据 (CrawlResult) 转换为 CSV 文件，支持 Excel 兼容的 UTF-8-BOM 编码。
每个数据类型生成一个独立 CSV：discussions / articles / news / notices。

CSV 列设计：

┌──────────────────────────────────────────────────────────────┐
│ discussions.csv                                              │
│  author │ time │ content │ link │ is_column │                │
│  comment_count │ like_count │ forward_count                  │
├──────────────────────────────────────────────────────────────┤
│ articles.csv                                                 │
│  title │ author │ time │ content │ link │ comment_count │    │
│  like_count │ article_id                                     │
├──────────────────────────────────────────────────────────────┤
│ news.csv                                                     │
│  title │ time │ source │ content │ link                      │
├──────────────────────────────────────────────────────────────┤
│ notices.csv                                                  │
│  title │ time │ link │ pdf_link │ notice_type │ content      │
└──────────────────────────────────────────────────────────────┘
"""

import csv
import logging
from pathlib import Path
from typing import Optional

from .models import CrawlResult

logger = logging.getLogger(__name__)


# ── CSV column definitions ──────────────────────────────────────────────────

_COLUMNS = {
    "discussions": [
        "author", "time", "content",
        "comment_count", "like_count", "forward_count",
        "is_column", "link",
    ],
    "articles": [
        "title", "author", "time", "content",
        "comment_count", "like_count",
        "article_id", "link",
    ],
    "news": [
        "title", "time", "source", "content", "link",
    ],
    "notices": [
        "title", "time", "notice_type", "content",
        "link", "pdf_link",
    ],
}


def _safe_str(value, max_len: int = 50000) -> str:
    """Convert value to safe CSV string, truncate very long content."""
    s = str(value) if value is not None else ""
    if len(s) > max_len:
        s = s[:max_len] + "…[truncated]"
    return s


def _write_csv(path: Path, columns: list, rows: list, symbol: str):
    """Write CSV with UTF-8-BOM for Excel compatibility."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        for row in rows:
            writer.writerow([row.get(col, "") for col in columns])
    logger.info(f"CSV 已导出: {path} ({len(rows)} 行)")


def export_csv(
    result: CrawlResult,
    output_dir: str | Path,
    prefix: Optional[str] = None,
) -> dict:
    """将 CrawlResult 导出为 4 个 CSV 文件。

    Args:
        result: 爬取结果
        output_dir: 输出目录
        prefix: 文件名前缀（默认: {symbol}_data_{timestamp}）

    Returns:
        {csv_type: file_path} 映射

    Raises:
        ValueError: 数据为空时抛出
    """
    import time as _time

    output_dir = Path(output_dir)
    prefix = prefix or f"{result.symbol}_data_{_time.strftime('%Y%m%d_%H%M%S')}"

    # Total data check
    total = (len(result.discussions) + len(result.articles) +
             len(result.news) + len(result.notices))
    if total == 0:
        raise ValueError(f"没有数据可导出: {result.symbol}")

    files = {}

    # Discussions
    if result.discussions:
        rows = []
        for d in result.discussions:
            rows.append({
                "author": d.author or "",
                "time": d.time or "",
                "content": _safe_str(d.content, 30000),
                "comment_count": d.comment_count,
                "like_count": d.like_count,
                "forward_count": d.forward_count,
                "is_column": "是" if d.is_column else "否",
                "link": d.link or "",
            })
        path = output_dir / f"{prefix}_discussions.csv"
        _write_csv(path, _COLUMNS["discussions"], rows, result.symbol)
        files["discussions"] = str(path)

    # Articles
    if result.articles:
        rows = []
        for a in result.articles:
            rows.append({
                "title": a.title or "",
                "author": a.author or "",
                "time": a.time or "",
                "content": _safe_str(a.content, 50000),
                "comment_count": a.comment_count,
                "like_count": a.like_count,
                "article_id": getattr(a, "article_id", "") or "",
                "link": a.link or "",
            })
        path = output_dir / f"{prefix}_articles.csv"
        _write_csv(path, _COLUMNS["articles"], rows, result.symbol)
        files["articles"] = str(path)

    # News
    if result.news:
        rows = []
        for n in result.news:
            rows.append({
                "title": n.title or "",
                "time": n.time or "",
                "source": n.source or "",
                "content": _safe_str(n.content, 30000),
                "link": n.link or "",
            })
        path = output_dir / f"{prefix}_news.csv"
        _write_csv(path, _COLUMNS["news"], rows, result.symbol)
        files["news"] = str(path)

    # Notices
    if result.notices:
        rows = []
        for nt in result.notices:
            rows.append({
                "title": nt.title or "",
                "time": nt.time or "",
                "notice_type": nt.notice_type or "",
                "content": _safe_str(nt.content, 30000),
                "link": nt.link or "",
                "pdf_link": nt.pdf_link or "",
            })
        path = output_dir / f"{prefix}_notices.csv"
        _write_csv(path, _COLUMNS["notices"], rows, result.symbol)
        files["notices"] = str(path)

    logger.info(f"CSV 导出完成: {len(files)} 文件, {total} 条记录")
    return files


def export_csv_from_json(json_path: str | Path,
                         output_dir: str | Path) -> dict:
    """从已保存的 JSON 数据文件导出 CSV。

    Args:
        json_path: CrawlResult JSON 文件路径
        output_dir: CSV 输出目录

    Returns:
        {csv_type: file_path} 映射
    """
    import json

    with open(json_path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    result = CrawlResult.from_dict(raw)
    prefix = Path(json_path).stem
    return export_csv(result, output_dir, prefix=prefix)
