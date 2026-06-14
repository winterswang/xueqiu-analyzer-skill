"""Tests for crawler.py text cleaning utilities."""

import pytest
from xueqiu_analyzer.crawler import clean_pua


class TestCleanPua:
    """Verify PUA and invisible-formatting character removal."""

    def test_strips_icon_font_chars(self):
        """\ue62d \ue64b \ue633 \ue62f — xueqiu's common icon font glyphs."""
        raw = "海外市场\uE62D\uE64B讨论\uE633"
        assert clean_pua(raw) == "海外市场讨论"

    def test_invisible_formatting(self):
        """U+200B (zero-width space) and friends."""
        raw = "hello\u200Bworld\u200Ctest\u200D!"
        assert clean_pua(raw) == "helloworldtest!"

    def test_preserves_normal_text(self):
        text = "贵州茅台2024年报：营收增长15%"
        assert clean_pua(text) == text

    def test_empty_string(self):
        assert clean_pua("") == ""

    def test_only_pua_chars(self):
        assert clean_pua("\uE62D\uE64B") == ""

    def test_mixed_pua_and_formatting(self):
        """Both PUA and invisible formatting in one string."""
        raw = "\uE62D点赞\u200B\uE64B转发\u200C\uE633"
        assert clean_pua(raw) == "点赞转发"

    def test_idempotent(self):
        """Re-cleaning should be a no-op."""
        text = "clean text already"
        assert clean_pua(clean_pua(text)) == text


class TestApiDiagnostics:
    """Verify non-JSON API diagnostics are actionable and secret-safe."""

    class DummyResponse:
        def __init__(self, text='', status_code=200, content_type='text/html'):
            self.text = text
            self.status_code = status_code
            self.headers = {'content-type': content_type}
            self.content = text.encode('utf-8')

        def json(self):
            raise ValueError('Expecting value: line 1 column 1 (char 0)')

    def test_non_json_login_html_diagnostic_redacts_token(self, caplog):
        from xueqiu_analyzer.crawler import _json_or_log_diagnostic

        resp = self.DummyResponse('<html>用户登录 token=SECRET123</html>')
        url = 'https://xueqiu.com/query?xq_a_token=SECRET456&symbol=PDD'

        with caplog.at_level('WARNING'):
            data = _json_or_log_diagnostic(resp, __import__('logging').getLogger('test'), '讨论', url)

        assert data is None
        assert 'status=200' in caplog.text
        assert 'content_type=' in caplog.text
        assert 'reason=login_html' in caplog.text
        assert 'body_head=' in caplog.text
        assert 'SECRET123' not in caplog.text
        assert 'SECRET456' not in caplog.text
        assert 'xq_a_token=<redacted>' in caplog.text

    def test_non_json_empty_body_classification(self):
        from xueqiu_analyzer.crawler import _classify_non_json_response

        resp = self.DummyResponse('', content_type='application/json')
        assert _classify_non_json_response(resp, '') == 'empty_body'

    def test_non_json_captcha_classification(self):
        from xueqiu_analyzer.crawler import _classify_non_json_response

        resp = self.DummyResponse('<html>安全验证 验证码</html>', content_type='text/html')
        assert _classify_non_json_response(resp, resp.text) == 'captcha_html'
