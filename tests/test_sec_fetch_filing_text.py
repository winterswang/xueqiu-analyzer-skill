"""fetch_filing_text 的两处修补（issue #44 / #45）。

- #44：accession 匹配不到时**不再**退回 `filings[0]`。那份只是同表单里最新的
  一份，把它的正文挂到当前公告上等于静默张冠李戴，还会流进报告。
- #45：`timeout` 参数此前没有任何效果，现在落到 edgar 的 HTTP 层。

edgar 用假模块替身，不联网、不依赖真库版本。
"""

import sys
import types

from xueqiu_analyzer import sec_fetcher

LONG_BODY = "Item 7. Management's discussion and analysis. " * 20


class _FakeFiling:
    def __init__(self, accession_number, text):
        self.accession_number = accession_number
        self._text = text

    def text(self):
        return self._text


class _FakeCompany:
    def __init__(self, filings):
        self._filings = filings

    def get_all_filings(self, form=None):
        return self._filings


def _install_fake_edgar(monkeypatch, filings, sink):
    """把 `import edgar` 换成替身，记录 configure_http 收到的参数。"""
    fake = types.ModuleType("edgar")
    fake.Company = lambda *a, **k: _FakeCompany(filings)
    fake.set_identity = lambda *a, **k: None

    def _configure_http(**kwargs):
        sink["configure_http"] = kwargs

    fake.configure_http = _configure_http
    monkeypatch.setitem(sys.modules, "edgar", fake)
    return fake


class TestAccessionMatch:
    def test_returns_the_matching_filing(self, monkeypatch):
        sink = {}
        wanted = _FakeFiling("0001104659-26-067186", LONG_BODY)
        other = _FakeFiling("0001104659-26-099999", "另一份 filing 的正文")
        _install_fake_edgar(monkeypatch, [other, wanted], sink)

        text = sec_fetcher.fetch_filing_text("PDD", "6-K", "0001104659-26-067186")

        assert text and "Management's discussion" in text

    def test_missing_accession_returns_none_instead_of_other_filing(self, monkeypatch):
        """结果里有别的 filing，但目标 accession 不存在 → 必须返回 None。"""
        sink = {}
        other = _FakeFiling("0001104659-26-099999", "另一份 filing 的正文")
        _install_fake_edgar(monkeypatch, [other], sink)

        text = sec_fetcher.fetch_filing_text("PDD", "6-K", "0001104659-26-067186")

        assert text is None, "不得把另一份 filing 的正文当成目标公告的正文"

    def test_accession_formatting_differences_still_match(self, monkeypatch):
        """edgartools 字段可能不带连字符，归一化后仍要命中。"""
        sink = {}
        filing = _FakeFiling("000110465926067186", LONG_BODY)
        _install_fake_edgar(monkeypatch, [filing], sink)

        text = sec_fetcher.fetch_filing_text("PDD", "6-K", "0001104659-26-067186")

        assert text and "Management's discussion" in text

    def test_no_filings_returns_none(self, monkeypatch):
        sink = {}
        _install_fake_edgar(monkeypatch, [], sink)

        assert sec_fetcher.fetch_filing_text("PDD", "6-K", "0001104659-26-067186") is None


class TestTimeoutApplied:
    def test_timeout_reaches_edgar_http_layer(self, monkeypatch):
        sink = {}
        _install_fake_edgar(monkeypatch, [_FakeFiling("acc-1", LONG_BODY)], sink)

        sec_fetcher.fetch_filing_text("PDD", "6-K", "acc-1", timeout=17)

        assert sink.get("configure_http") == {"timeout": 17}

    def test_default_timeout_is_60(self, monkeypatch):
        sink = {}
        _install_fake_edgar(monkeypatch, [_FakeFiling("acc-1", LONG_BODY)], sink)

        sec_fetcher.fetch_filing_text("PDD", "6-K", "acc-1")

        assert sink.get("configure_http") == {"timeout": 60}

    def test_older_edgar_without_configure_http_still_works(self, monkeypatch):
        """老版本没有 configure_http —— 不能因此报错，正文照常返回。"""
        sink = {}
        fake = _install_fake_edgar(monkeypatch, [_FakeFiling("acc-1", LONG_BODY)], sink)
        del fake.configure_http

        text = sec_fetcher.fetch_filing_text("PDD", "6-K", "acc-1", timeout=5)

        assert text and "Management's discussion" in text
        assert sink == {}
