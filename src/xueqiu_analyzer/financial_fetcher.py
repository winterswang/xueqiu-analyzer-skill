"""
xueqiu-analyzer V3 — 财务数据获取

数据源：
1. 雪球 API — PE/PB/ROE/市值/52周高低
2. AkShare — 毛利率/净利率/营收增速/利润增速
3. akshare_service — 多年 ROIC 趋势

所有数据源降级兼容：任一不可用时跳过，不影响主流程。
"""

import json
import logging
import urllib.request
from typing import Dict, List, Optional
from datetime import datetime

from .models import FinancialData

logger = logging.getLogger(__name__)


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


def normalize_symbol(symbol: str, market: str) -> str:
    """标准化股票代码（用于 AkShare）"""
    symbol = symbol.upper().strip()
    if market == 'A股' and (symbol.startswith('SH') or symbol.startswith('SZ')):
        return symbol[2:]
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


class FinancialFetcher:
    """财务数据获取器 — 输出 V3 FinancialData"""

    def __init__(self):
        self.xueqiu_api = XueqiuFinancialAPI()
        self._akshare_ok = self._check_akshare()
        self._akshare_svc_ok = self._check_akshare_service()

    def _check_akshare(self) -> bool:
        try:
            import akshare  # noqa: F401
            return True
        except ImportError:
            logger.info("AkShare 未安装，毛利率/净利率数据不可用")
            return False

    def _check_akshare_service(self) -> bool:
        try:
            from akshare_service.skills.finance import calculate_roic  # noqa
            return True
        except ImportError:
            logger.info("akshare_service 未安装，多年 ROIC 数据不可用")
            return False

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

        # 1. 雪球 API
        if cookies:
            self.xueqiu_api.set_cookies(cookies)
            quote = self.xueqiu_api.fetch_quote(symbol)
            if quote:
                result.pe_ttm = _safe_float(quote.get('pe_ttm'))
                result.pb = _safe_float(quote.get('pb'))
                result.market_cap = _safe_float(quote.get('market_capital'))
                result.low52w = _safe_float(quote.get('low52w'))
                result.high52w = _safe_float(quote.get('high52w'))

                # 计算 ROE
                profit = _safe_float(quote.get('profit'))
                equity = _safe_float(quote.get('shareholder_funds'))
                if profit and equity:
                    result.roe = (profit / equity) * 100

                source_parts.append('雪球')
                logger.info(f"  雪球: PE={result.pe_ttm:.1f}, "
                            f"PB={result.pb:.1f}, ROE={result.roe:.1f}%")

        # 2. 多年 ROIC
        yearly_roic = self._fetch_multi_year_roic(symbol)
        if yearly_roic:
            result.yearly_roic = yearly_roic
            source_parts.append('AkShareService')

        # 3. AkShare 补充（毛利率等）
        akshare_data = self._fetch_akshare_supplement(symbol)
        if akshare_data:
            result.gross_margin = akshare_data.get('gross_margin', 0)
            result.net_margin = akshare_data.get('net_margin', 0)
            result.revenue_growth = akshare_data.get('revenue_growth', 0)
            result.profit_growth = akshare_data.get('profit_growth', 0)
            source_parts.append('AkShare')
            logger.info(f"  AkShare: 毛利率={result.gross_margin:.1f}%, "
                        f"净利率={result.net_margin:.1f}%")

        if result.has_data:
            logger.info(f"  财务数据来源: {'+'.join(source_parts)}")
            return result

        logger.warning("  财务数据获取失败")
        return None

    def _fetch_multi_year_roic(self, symbol: str) -> List[Dict]:
        """获取多年 ROIC 数据"""
        if not self._akshare_svc_ok:
            return []
        try:
            from akshare_service.skills.finance import calculate_roic
            market = detect_market(symbol)
            code = normalize_symbol(symbol, market)
            logger.info(f"  获取 {market} {code} 的 5 年 ROIC...")
            df = calculate_roic(market=market, code=code, years=5)
            if df is not None and not df.empty:
                records = df.to_dict('records')
                logger.info(f"  ✅ 获取到 {len(records)} 年 ROIC 数据")
                return records
        except Exception as e:
            logger.warning(f"  ROIC 获取失败: {e}")
        return []

    def _fetch_akshare_supplement(self, symbol: str) -> Optional[dict]:
        """从 AkShare 获取补充数据（毛利率/净利率等）"""
        if not self._akshare_ok:
            return None
        # 仅美股
        market = detect_market(symbol)
        if market != '美股':
            return None
        try:
            import akshare as ak
            df = ak.stock_financial_us_analysis_indicator_em(
                symbol=symbol, indicator="年报")
            if df is not None and not df.empty:
                latest = df.iloc[0]
                return {
                    'gross_margin': _safe_float(
                        latest.get('GROSS_PROFIT_RATIO')),
                    'net_margin': _safe_float(
                        latest.get('NET_PROFIT_RATIO')),
                    'revenue_growth': _safe_float(
                        latest.get('OPERATE_INCOME_YOY')),
                    'profit_growth': _safe_float(
                        latest.get('PARENT_HOLDER_NETPROFIT_YOY')),
                }
        except Exception as e:
            logger.warning(f"  AkShare 补充数据获取失败: {e}")
        return None


def _safe_float(val) -> float:
    """安全转换为 float"""
    if val is None:
        return 0.0
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0
