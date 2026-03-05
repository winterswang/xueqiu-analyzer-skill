#!/usr/bin/env python3
"""
财务数据获取模块

数据源优先级：
1. 雪球 API（PE、PB、ROE计算、K线等）
2. AkShare（毛利率、净利率等补充）
"""

import os
import sys
import json
import urllib.request
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from datetime import datetime


@dataclass
class FinancialData:
    """财务数据"""
    symbol: str
    name: str = ""
    # 估值指标（雪球 API）
    pe_ttm: float = 0.0  # 市盈率 TTM
    pe_lyr: float = 0.0  # 市盈率 LYR
    pb: float = 0.0  # 市净率
    # 价格信息（雪球 API）
    current_price: float = 0.0  # 当前价
    market_cap: float = 0.0  # 总市值
    high52w: float = 0.0  # 52周最高
    low52w: float = 0.0  # 52周最低
    # 盈利指标（雪球 API）
    eps: float = 0.0  # 每股收益
    profit: float = 0.0  # 净利润
    shareholder_funds: float = 0.0  # 股东权益
    roe: float = 0.0  # ROE（计算：净利润/股东权益）
    # 补充指标（AkShare）
    gross_margin: float = 0.0  # 毛利率
    net_margin: float = 0.0  # 净利率
    akshare_roe: float = 0.0  # AkShare ROE
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


class FinancialDataFetcher:
    """财务数据获取器"""
    
    def __init__(self):
        self.xueqiu_api = XueqiuFinancialAPI()
        self.akshare_available = self._check_akshare()
    
    def _check_akshare(self) -> bool:
        """检查 AkShare 是否可用"""
        try:
            import akshare as ak
            return True
        except ImportError:
            print("⚠️ AkShare 未安装")
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
        
        # 2. 从 AkShare 获取毛利率等补充数据
        if self.akshare_available:
            try:
                import akshare as ak
                
                # 美股
                if not symbol.isdigit():
                    df = ak.stock_financial_us_analysis_indicator_em(symbol=symbol, indicator="年报")
                    if df is not None and not df.empty:
                        latest = df.iloc[0]
                        result.gross_margin = float(latest.get('GROSS_PROFIT_RATIO', 0) or 0)
                        result.net_margin = float(latest.get('NET_PROFIT_RATIO', 0) or 0)
                        result.akshare_roe = float(latest.get('ROE_AVG', 0) or 0)
                        result.source += '+AkShare'
                        print(f"  AkShare数据: 毛利率={result.gross_margin:.1f}%, 净利率={result.net_margin:.1f}%")
            except Exception as e:
                print(f"  AkShare 获取失败: {e}")
        
        result.fetch_time = datetime.now().isoformat()
        
        return result if result.pe_ttm or result.roe else None
    
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