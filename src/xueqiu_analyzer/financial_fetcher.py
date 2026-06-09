"""
xueqiu-analyzer V3 — 财务数据获取

数据源：
1. 雪球 API — PE/PB/市值/52周高低
2. financial-sdk — 毛利率/净利率/ROE/ROIC/营收增速/利润增速/Piotroski

所有数据源降级兼容：任一不可用时跳过，不影响主流程。
"""

import json
import logging
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime

from .models import FinancialData

logger = logging.getLogger(__name__)

# financial-sdk CLI 路径 —— 优先环境变量 FINANCIAL_SDK_DIR
_FINANCIAL_SDK_DIR = Path(
    os.environ.get("FINANCIAL_SDK_DIR", str(Path.home() / "code" / "financial-sdk"))
)
_FINANCIAL_SDK_CLI = _FINANCIAL_SDK_DIR / "src" / "financial_sdk_cli.py"
_FINANCIAL_SDK_PYTHON = Path(sys.executable)  # 使用当前 Python，不依赖 .venv


def detect_market(symbol: str) -> str:
    """检测市场类型"""
    symbol = symbol.upper().strip()
    if symbol.startswith('SH') or symbol.startswith('SZ'):
        return 'A股'
    if len(symbol) == 6 and symbol[0] in '036':
        return 'A股'
    if len(symbol) == 5 and symbol.isdigit():
        return '港股'
    if symbol.isalpha():
        return '美股'
    return 'A股'


def to_finsdk_symbol(symbol: str, market: str = None) -> str:
    """转换股票代码为 financial-sdk 格式

    TCOM → TCOM, 00700 → 0700.HK, SH600519 → 600519.SH
    """
    symbol = symbol.upper().strip()
    market = market or detect_market(symbol)

    if market == 'A股':
        # SH600000 → 600000.SH, SZ000001 → 000001.SZ
        m = re.match(r'^(SH|SZ)(\d{6})$', symbol)
        if m:
            return f"{m.group(2)}.{m.group(1)}"
        return f"{symbol}.SH"

    if market == '港股':
        # 00700 → 0700.HK
        return f"{int(symbol):04d}.HK"

    # 美股：原样
    return symbol


class XueqiuFinancialAPI:
    """雪球财务数据 API"""

    def __init__(self):
        self.cookie_str = ""

    def set_cookies(self, cookies: list):
        """设置 cookies"""
        self.cookie_str = '; '.join(
            [f"{c['name']}={c['value']}" for c in cookies])

    def fetch_quote(self, symbol: str) -> Optional[dict]:
        """获取股票报价信息"""
        url = (f'https://stock.xueqiu.com/v5/stock/quote.json'
               f'?symbol={symbol}&extend=detail')
        try:
            req = urllib.request.Request(url, headers={
                'Cookie': self.cookie_str,
                'User-Agent': ('Mozilla/5.0 (Macintosh; Intel Mac OS X '
                               '10_15_7) AppleWebKit/537.36'),
            })
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                return data.get('data', {}).get('quote', {})
        except Exception as e:
            logger.warning(f"雪球 API 获取失败: {e}")
            return None


class FinancialSDKClient:
    """financial-sdk CLI 封装"""

    def _check_available(self) -> bool:
        """检查 financial-sdk 是否可用"""
        return (_FINANCIAL_SDK_PYTHON.exists()
                and _FINANCIAL_SDK_CLI.exists())

    def analyze(self, symbol: str) -> Optional[dict]:
        """调用 financial-sdk analyze 获取完整指标"""
        if not self._check_available():
            logger.info("financial-sdk 未安装，财务指标数据不可用")
            return None

        finsdk_symbol = to_finsdk_symbol(symbol)
        try:
            result = subprocess.run(
                [_FINANCIAL_SDK_PYTHON, _FINANCIAL_SDK_CLI,
                 "analyze", finsdk_symbol, "--format", "json"],
                capture_output=True, text=True,
                timeout=60, cwd=_FINANCIAL_SDK_DIR,
            )
            if result.returncode != 0:
                logger.warning(f"financial-sdk 调用失败: {result.stderr[:200]}")
                return None

            # 过滤掉 stderr 混入的警告行
            stdout = result.stdout
            # 找第一个 { 开始解析 JSON
            json_start = stdout.find('{')
            if json_start < 0:
                return None
            return json.loads(stdout[json_start:])

        except subprocess.TimeoutExpired:
            logger.warning("financial-sdk 调用超时")
            return None
        except Exception as e:
            logger.warning(f"financial-sdk 调用异常: {e}")
            return None


class FinancialFetcher:
    """财务数据获取器 — 输出 V3 FinancialData"""

    def __init__(self):
        self.xueqiu_api = XueqiuFinancialAPI()
        self.finsdk = FinancialSDKClient()

    def fetch(self, symbol: str, cookies: list = None) -> Optional[FinancialData]:
        """
        获取财务数据

        Args:
            symbol: 股票代码
            cookies: 雪球 cookies（用于雪球 API）

        Returns:
            FinancialData 或 None
        """
        result = FinancialData()
        source_parts = []

        # 1. 雪球 API — PE/PB/市值/52周高低
        if cookies:
            self.xueqiu_api.set_cookies(cookies)
            quote = self.xueqiu_api.fetch_quote(symbol)
            if quote:
                result.pe_ttm = _safe_float(quote.get('pe_ttm'))
                result.pb = _safe_float(quote.get('pb'))
                result.market_cap = _safe_float(quote.get('market_capital'))
                result.low52w = _safe_float(quote.get('low52w'))
                result.high52w = _safe_float(quote.get('high52w'))

                source_parts.append('雪球')
                logger.info(f"  雪球: PE={result.pe_ttm:.1f}, "
                            f"PB={result.pb:.1f}")

                # 雪球 ROE fallback（financial-sdk 不可用时的备选）
                profit = _safe_float(quote.get('profit'))
                equity = _safe_float(quote.get('shareholder_funds'))
                if profit and equity:
                    result._xueqiu_roe = (profit / equity) * 100

        # 2. financial-sdk — 毛利率/净利率/ROE/ROIC/增速
        finsdk_data = self._fetch_finsdk_metrics(symbol)
        if finsdk_data:
            result.gross_margin = finsdk_data.get('gross_margin', 0)
            result.net_margin = finsdk_data.get('net_margin', 0)
            result.revenue_growth = finsdk_data.get('revenue_growth', 0)
            result.profit_growth = finsdk_data.get('profit_growth', 0)
            result.yearly_roic = finsdk_data.get('yearly_roic', [])

            # ROE: financial-sdk 优先（更准确），雪球作 fallback
            if finsdk_data.get('roe', 0) > 0:
                result.roe = finsdk_data['roe']
            elif getattr(result, '_xueqiu_roe', 0) > 0:
                result.roe = result._xueqiu_roe

            source_parts.append('financial-sdk')
            logger.info(f"  financial-sdk: 毛利率={result.gross_margin:.1f}%, "
                        f"净利率={result.net_margin:.1f}%, "
                        f"ROE={result.roe:.1f}%, "
                        f"ROIC={finsdk_data.get('roic', 0):.1f}%")

        if result.has_data:
            logger.info(f"  财务数据来源: {'+'.join(source_parts)}")
            return result

        logger.warning("  财务数据获取失败")
        return None

    def _fetch_finsdk_metrics(self, symbol: str) -> Optional[dict]:
        """从 financial-sdk 获取核心财务指标"""
        data = self.finsdk.analyze(symbol)
        if not data:
            return None

        profitability = data.get('profitability') or {}
        growth = data.get('growth') or {}

        return {
            'gross_margin': _pct(profitability.get('gross_margin')),
            'net_margin': _pct(profitability.get('net_margin')),
            'roe': _pct(profitability.get('roe')),
            'roic': _pct(profitability.get('roic')),
            'revenue_growth': _pct(growth.get('revenue_growth_yoy')),
            'profit_growth': _pct(growth.get('profit_growth_yoy')),
            'yearly_roic': [],  # V3 models 暂用空列表
        }


def _safe_float(val) -> float:
    """安全转换为 float"""
    if val is None:
        return 0.0
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


def _pct(val) -> float:
    """financial-sdk 返回 0-1 ratio，转为百分比（如 0.196 → 19.6）

    安全下限：值 < 0.001 时直接返回 0（避免噪声）。
    值为 >= 1 时认为已是百分比，原样返回。
    """
    v = _safe_float(val)
    if v < 0.001:
        return 0.0
    if v < 1:
        return v * 100
    return v
