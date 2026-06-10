"""SEC EDGAR filing 正文下载器。

通过 edgartools 按 ticker + form_type + 日期范围搜索，
匹配 accession number 后下载 filing 全文并提取纯文本。
"""

import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ── 需要下载正文的高价值 form types ──
HIGH_VALUE_FORMS = frozenset({'6-K', '20-F', '8-K', '10-K', '10-Q'})

# ── 正则：从 opencli title 中提取 accession number ──
_ACCESSION_RE = re.compile(r'Accession\s+Number:\s*(\d{10}-\d{2}-\d{6})')

# ── 正则：提取行首 form type ──
_FORM_RE = re.compile(r'^([A-Z\d]+(?:[-/][A-Z\d]+)?)\s')


def extract_accession(title: str) -> Optional[str]:
    """从 opencli 返回的 title 中提取 SEC Accession Number。

    Args:
        title: opencli 公告 title 字符串

    Returns:
        Accession Number（如 '0001104659-26-067186'），未匹配返回 None
    """
    m = _ACCESSION_RE.search(title)
    return m.group(1) if m else None


def extract_form_type(title: str) -> Optional[str]:
    """从 opencli 返回的 title 中提取 SEC form type。

    Args:
        title: opencli 公告 title 字符串

    Returns:
        Form type（如 '6-K', '20-F'），未匹配返回 None
    """
    m = _FORM_RE.match(title)
    return m.group(1) if m else None


def is_high_value_filing(title: str) -> bool:
    """判断是否为高价值 filing（值得下载正文）。

    仅 6-K / 20-F / 8-K / 10-K / 10-Q 返回 True，
    Form 3/4/144 等低价值 filing 返回 False。

    Args:
        title: opencli 公告 title 字符串

    Returns:
        True 如果该 filing 属于高价值类型
    """
    ft = extract_form_type(title)
    return ft is not None and ft in HIGH_VALUE_FORMS


def _get_edgar_identity() -> str:
    """获取 SEC EDGAR 身份标识（邮箱格式）。"""
    import os
    try:
        from unified_downloader.core.config import get_default_config
        cfg = get_default_config()
        if cfg.edgar_identity:
            return cfg.edgar_identity
    except Exception:
        pass
    return os.environ.get(
        'EDGAR_IDENTITY',
        os.environ.get('USER', 'researcher') + '@example.com'
    )


def _clean_sec_text(text: str) -> str:
    """清理 SEC filing 文本中的 boilerplate 和格式噪音。

    - 去除残留 HTML/XBRL 标签
    - 压缩多余空行为双空行
    - 去除 SEC 标准 header
    """
    # 去除 HTML/XBRL 标签
    text = re.sub(r'<[^>]+>', '', text)
    # 压缩多余空行（3+ → 2）
    text = re.sub(r'\n{3,}', '\n\n', text)
    # 去除 SEC 标准 header 块
    text = re.sub(
        r'UNITED STATES\s+SECURITIES AND EXCHANGE COMMISSION.*?(?=\n[A-Z])',
        '',
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    return text.strip()


def fetch_filing_text(
    ticker: str,
    form_type: str,
    accession_number: str,
    filing_date: str = "",
    timeout: int = 60,
) -> Optional[str]:
    """从 SEC EDGAR 下载 filing 正文并提取纯文本。

    Args:
        ticker: 美股代码（如 'PDD'）
        form_type: SEC form type（如 '6-K'）
        accession_number: SEC accession number（如 '0001104659-26-067186'）
        filing_date: 公告日期（ISO 字符串，用于缩小搜索范围）
        timeout: 下载超时秒数

    Returns:
        filing 正文纯文本（已清理），失败返回 None
    """
    # ── Step 1: 初始化 edgar ──
    try:
        import edgar as _edgar_module
    except ImportError:
        logger.debug("edgartools 未安装，跳过 SEC 下载")
        return None

    try:
        identity = _get_edgar_identity()
        if hasattr(_edgar_module, 'set_identity'):
            try:
                _edgar_module.set_identity("XueqiuAnalyzer", identity)
            except TypeError:
                _edgar_module.set_identity(identity)
        else:
            from edgar import set_identity as _edgar_set_id
            _edgar_set_id(identity)
    except Exception as e:
        logger.warning(f"edgar set_identity 失败: {e}")
        # 非致命 — 部分版本可以不设 identity

    # ── Step 2: 搜索 filing ──
    try:
        from edgar import Company
    except ImportError:
        logger.warning("edgar.Company 导入失败")
        return None

    try:
        cik = accession_number.split('-')[0]
        # edgar 5.x: Company(name, cik); 4.x: Company(cik)
        try:
            company = Company(ticker, cik)
        except TypeError:
            company = Company(cik)

        filings = company.get_all_filings(form=form_type)
    except Exception as e:
        logger.warning(f"SEC 搜索失败 {ticker} {form_type}: {e}")
        return None

    if not filings:
        return None

    # ── Step 3: 匹配 accession number ──
    target_filing = None
    for f in filings:
        try:
            if getattr(f, 'accession_number', '') == accession_number:
                target_filing = f
                break
        except Exception:
            continue

    if target_filing is None:
        # 降级：取第一条（edgartools 默认按时间降序）
        try:
            target_filing = filings[0]
        except (IndexError, TypeError):
            pass

    if target_filing is None:
        return None

    # ── Step 4: 下载正文 ──
    try:
        if hasattr(target_filing, 'text'):
            full_text = target_filing.text()
        elif hasattr(target_filing, 'html'):
            from bs4 import BeautifulSoup  # noqa: PLC0415
            html = target_filing.html()
            soup = BeautifulSoup(html, 'html.parser')
            full_text = soup.get_text(separator='\n')
        else:
            logger.debug(f"filing 对象无 text/html 方法: {type(target_filing)}")
            return None
    except Exception as e:
        logger.warning(f"SEC 下载失败 {accession_number}: {e}")
        return None

    if not full_text or not full_text.strip():
        return None

    # ── Step 5: 清理与截断 ──
    full_text = _clean_sec_text(full_text)

    max_chars = 8000
    if len(full_text) > max_chars:
        full_text = full_text[:max_chars] + '\n[...SEC filing 正文已截断...]'

    return full_text
