"""Regression tests for to_finsdk_symbol / detect_market（issue #43）。

`detect_market()` 把 0/3/6 开头的 6 位代码都识别为 A 股，而 `to_finsdk_symbol()`
对**裸代码**一律追加 `.SH` —— 于是 `000001`、`300750` 被送去查沪市，
financial-sdk 取不到（或取错）标的，财务指标静默缺失。

行业惯例：沪市 6 开头，深市 0/3 开头。
"""

import pytest

from xueqiu_analyzer.financial_fetcher import detect_market, to_finsdk_symbol


class TestDetectMarket:
    @pytest.mark.parametrize("symbol", ["600519", "000001", "300750", "SH600519", "SZ000001"])
    def test_a_share(self, symbol):
        assert detect_market(symbol) == "A股"

    def test_hk_and_us(self):
        assert detect_market("00700") == "港股"
        assert detect_market("TCOM") == "美股"


class TestToFinsdkSymbol:
    """显式前缀必须原样保留，裸代码按首位推断交易所。"""

    @pytest.mark.parametrize("symbol,expected", [
        ("SH600519", "600519.SH"),   # 显式前缀优先
        ("SZ000001", "000001.SZ"),
        ("600519", "600519.SH"),     # 6 开头 → 沪市
        ("000001", "000001.SZ"),     # 0 开头 → 深市（issue #43 的原始症状）
        ("300750", "300750.SZ"),     # 3 开头 → 深市（创业板）
        ("002241", "002241.SZ"),
    ])
    def test_a_share(self, symbol, expected):
        assert to_finsdk_symbol(symbol) == expected

    def test_hk_strips_leading_zero(self):
        assert to_finsdk_symbol("00700") == "0700.HK"

    def test_us_unchanged(self):
        assert to_finsdk_symbol("TCOM") == "TCOM"

    def test_lowercase_and_whitespace_tolerated(self):
        assert to_finsdk_symbol(" sz000001 ") == "000001.SZ"
