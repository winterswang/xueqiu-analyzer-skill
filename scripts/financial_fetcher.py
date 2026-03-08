#!/usr/bin/env python3
"""
财务数据获取模块 V2.2

数据源：
1. 雪球 API（PE、PB、ROE计算、K线等）
2. AkShare（毛利率、净利率等补充）
3. akshare_service（多年ROIC等核心财务数据）
"""

import os
import sys
import json
import urllib.request
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict, field
from datetime import datetime

# 添加 akshare_docs 到路径
sys.path.insert(0, '/root/.openclaw/workspace/akshare_docs')


@dataclass
class YearlyFinancial:
    """单年财务数据"""
    year: int
    roic: float = 0.0
    nopat: float = 0.0  # 税后净营业利润（亿）
    invested_capital: float = 0.0  # 投入资本（亿）
    operate_profit: float = 0.0  # 营业利润（亿）
    net_profit: float = 0.0  # 净利润（亿）
    revenue: float = 0.0  # 营业收入（亿）


@dataclass
class FinancialData:
    """财务数据 V2.2"""
    symbol: str
    name: str = ""
    # 估值指标（雪球 API）
    pe_ttm: float = 0.0
    pe_lyr: float = 0.0
    pb: float = 0.0
    # 价格信息（雪球 API）
    current_price: float = 0.0
    market_cap: float = 0.0
    high52w: float = 0.0
    low52w: float = 0.0
    # 盈利指标（雪球 API）
    eps: float = 0.0
    profit: float = 0.0
    shareholder_funds: float = 0.0
    roe: float = 0.0
    # 补充指标（AkShare）
    gross_margin: float = 0.0
    net_margin: float = 0.0
    akshare_roe: float = 0.0
    # 增长指标
    revenue_growth: float = 0.0
    profit_growth: float = 0.0
    # 多年财务数据（V2.2 新增）
    yearly_roic: List[Dict] = field(default_factory=list)
    yearly_roic_available: bool = False
    # 数据来源
    source: str = ""
    fetch_time: str = ""


class XueqiuFinancialAPI:
    """雪球财务数据 API"""
    
    def __init__(self):
        self.cookie_str = ""
    
    def set_cookies(self, cookies: list):
        """设置 cookies"""
        self.cookie_str = '; '.join([f"{c['name']}={c['value']}" for c in cookies])
    
    def fetch_quote(self, symbol: str) -> Optional[dict]:
        """获取股票报价信息"""
        url = f'https://stock.xueqiu.com/v5/stock/quote.json?symbol={symbol}&extend=detail'
        
        try:
            req = urllib.request.Request(
                url,
                headers={
                    'Cookie': self.cookie_str,
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }
            )
            
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                return data.get('data', {}).get('quote', {})
        except Exception as e:
            print(f"雪球 API 获取失败: {e}")
            return None


def detect_market(symbol: str) -> str:
    """检测市场类型"""
    symbol = symbol.upper().strip()
    
    # A股：SH600989 或 600989 或 SZ300760
    if symbol.startswith('SH') or symbol.startswith('SZ'):
        return 'A股'
    if len(symbol) == 6 and symbol[0] in '036':
        return 'A股'
    
    # 港股：5位数字
    if len(symbol) == 5 and symbol.isdigit():
        return '港股'
    
    # 美股：字母
    if symbol.isalpha():
        return '美股'
    
    return 'A股'  # 默认


def normalize_symbol(symbol: str, market: str) -> str:
    """标准化股票代码"""
    symbol = symbol.upper().strip()
    
    if market == 'A股':
        # 去掉前缀，只保留6位代码
        if symbol.startswith('SH') or symbol.startswith('SZ'):
            return symbol[2:]
        return symbol
    elif market == '港股':
        return symbol
    elif market == '美股':
        return symbol
    
    return symbol


class FinancialDataFetcher:
    """财务数据获取器 V2.2"""
    
    def __init__(self):
        self.xueqiu_api = XueqiuFinancialAPI()
        self.akshare_available = self._check_akshare()
        self.akshare_service_available = self._check_akshare_service()
    
    def _check_akshare(self) -> bool:
        """检查 AkShare 是否可用"""
        try:
            import akshare as ak
            return True
        except ImportError:
            print("⚠️ AkShare 未安装")
            return False
    
    def _check_akshare_service(self) -> bool:
        """检查 akshare_service 是否可用"""
        try:
            from akshare_service.skills.finance import calculate_roic
            return True
        except ImportError:
            print("⚠️ akshare_service 未安装")
            return False
    
    def fetch_multi_year_roic(self, symbol: str, years: int = 5) -> List[Dict]:
        """
        获取多年 ROIC 数据
        
        Args:
            symbol: 股票代码
            years: 年数（默认5年）
            
        Returns:
            多年财务数据列表
        """
        if not self.akshare_service_available:
            return []
        
        try:
            from akshare_service.skills.finance import calculate_roic
            
            market = detect_market(symbol)
            code = normalize_symbol(symbol, market)
            
            print(f"  获取 {market} {code} 的 {years} 年 ROIC 数据...")
            
            df = calculate_roic(market=market, code=code, years=years)
            
            if df is not None and not df.empty:
                result = df.to_dict('records')
                print(f"  ✅ 获取到 {len(result)} 年 ROIC 数据")
                return result
            else:
                print(f"  ⚠️ 未获取到 ROIC 数据")
                return []
                
        except Exception as e:
            print(f"  ❌ ROIC 获取失败: {e}")
            return []
    
    def fetch(self, symbol: str, cookies: list = None) -> Optional[FinancialData]:
        """
        获取财务数据 V2.2
        
        Args:
            symbol: 股票代码
            cookies: 雪球 cookies（用于雪球 API）
            
        Returns:
            FinancialData 或 None
        """
        result = FinancialData(symbol=symbol)
        
        # 1. 从雪球 API 获取主要数据
        if cookies:
            self.xueqiu_api.set_cookies(cookies)
            quote = self.xueqiu_api.fetch_quote(symbol)
            
            if quote:
                result.name = quote.get('name', '')
                result.current_price = float(quote.get('current', 0) or 0)
                result.pe_ttm = float(quote.get('pe_ttm', 0) or 0)
                result.pe_lyr = float(quote.get('pe_lyr', 0) or 0)
                result.pb = float(quote.get('pb', 0) or 0)
                result.market_cap = float(quote.get('market_capital', 0) or 0)
                result.high52w = float(quote.get('high52w', 0) or 0)
                result.low52w = float(quote.get('low52w', 0) or 0)
                result.eps = float(quote.get('eps', 0) or 0)
                result.profit = float(quote.get('profit', 0) or 0)
                result.shareholder_funds = float(quote.get('shareholder_funds', 0) or 0)
                
                # 计算 ROE
                if result.profit and result.shareholder_funds:
                    result.roe = (result.profit / result.shareholder_funds) * 100
                
                result.source = '雪球'
                print(f"  雪球数据: PE={result.pe_ttm:.1f}, PB={result.pb:.1f}, ROE={result.roe:.1f}%")
        
        # 2. 从 akshare_service 获取多年 ROIC（V2.2 新增）
        yearly_roic = self.fetch_multi_year_roic(symbol, years=5)
        if yearly_roic:
            result.yearly_roic = yearly_roic
            result.yearly_roic_available = True
            result.source += '+AkShareService'
        
        # 3. 从 AkShare 获取毛利率等补充数据（仅美股）
        if self.akshare_available and not symbol.isdigit() and not symbol.startswith(('SH', 'SZ')):
            try:
                import akshare as ak
                
                df = ak.stock_financial_us_analysis_indicator_em(symbol=symbol, indicator="年报")
                if df is not None and not df.empty:
                    latest = df.iloc[0]
                    result.gross_margin = float(latest.get('GROSS_PROFIT_RATIO', 0) or 0)
                    result.net_margin = float(latest.get('NET_PROFIT_RATIO', 0) or 0)
                    result.akshare_roe = float(latest.get('ROE_AVG', 0) or 0)
                    result.revenue_growth = float(latest.get('OPERATE_INCOME_YOY', 0) or 0)
                    result.profit_growth = float(latest.get('PARENT_HOLDER_NETPROFIT_YOY', 0) or 0)
                    result.source += '+AkShare'
                    print(f"  AkShare数据: 毛利率={result.gross_margin:.1f}%, 净利率={result.net_margin:.1f}%")
            except Exception as e:
                print(f"  AkShare 获取失败: {e}")
        
        result.fetch_time = datetime.now().isoformat()
        
        return result if result.pe_ttm or result.roe or result.yearly_roic_available else None
    
    def to_dict(self, data: FinancialData) -> dict:
        """转换为字典"""
        return asdict(data)


def main():
    """测试"""
    import argparse
    
    parser = argparse.ArgumentParser(description='财务数据获取')
    parser.add_argument('symbol', help='股票代码')
    
    args = parser.parse_args()
    
    fetcher = FinancialDataFetcher()
    result = fetcher.fetch(args.symbol)
    
    if result:
        print(json.dumps(fetcher.to_dict(result), ensure_ascii=False, indent=2))
    else:
        print("获取失败")


if __name__ == '__main__':
    main()