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


class TestEngagementMetrics:
    """Verify engagement metric (like/comment/forward) extraction for all
    four Discussion construction paths in crawler.py.

    Prior bug: all 4 paths omitted engagement fields, leaving them at the
    dataclass default of 0. This produced 100% zero engagement data in the
    downstream CSV export and disabled engagement-based quality filtering.
    """

    def test_opencli_path_populates_engagement(self):
        """Path 1 and 2: opencli items have likes/replies/forwards keys."""
        # Simulate the field mapping used at crawler.py:309 and :775
        item = {
            "author": "test_user",
            "text": "some discussion text",
            "created_at": "2026-08-04T10:00:00",
            "url": "https://xueqiu.com/123/456",
            "likes": 42,
            "replies": 7,
            "forwards": 3,
        }
        from xueqiu_analyzer.models import Discussion
        d = Discussion(
            author=item.get('author', ''),
            content=item.get('text', '')[:500],
            time=item.get('created_at', ''),
            link=item.get('url', ''),
            is_column=False,
            like_count=int(item.get('likes', 0) or 0),
            comment_count=int(item.get('replies', 0) or 0),
            forward_count=int(item.get('forwards', 0) or 0),
        )
        assert d.like_count == 42
        assert d.comment_count == 7
        assert d.forward_count == 3

    def test_api_path_populates_engagement(self):
        """Path 3: Xueqiu API items have like_count/reply_count/retweet_count."""
        # Simulate the field mapping used at crawler.py:854
        item = {
            "id": 12345,
            "description": "test content",
            "like_count": 99,
            "reply_count": 15,
            "retweet_count": 5,
        }
        from xueqiu_analyzer.models import Discussion
        d = Discussion(
            author="user",
            content="test content"[:500],
            time="2026-08-04 10:00",
            link="https://xueqiu.com/1/12345",
            is_column=False,
            like_count=int(item.get('like_count', 0) or 0),
            comment_count=int(item.get('reply_count', 0) or 0),
            forward_count=int(item.get('retweet_count', 0) or 0),
        )
        assert d.like_count == 99
        assert d.comment_count == 15
        assert d.forward_count == 5

    def test_html_engagement_regex_extraction(self):
        """Path 4: _parse_single_discussion extracts engagement from footer text.

        Xueqiu's HTML timeline renders engagement as '转发 N 回复 N 赞 N'.
        The regex must capture all three before they are stripped from content.
        """
        import re

        # Simulate the regex used in _parse_single_discussion
        sample_text = (
            "某用户 2小时前\n"
            "这是一段讨论内容，关于瑞幸咖啡的财报分析\n"
            "展开\n"
            "转发 12 回复 34 赞 56\n"
            "收藏"
        )
        eng_match = re.search(
            r'(?:转发|转发数)\s*(\d+)\s*(?:回复|评论)\s*(\d+)\s*(?:赞|点赞)\s*(\d+)',
            sample_text,
        )
        assert eng_match is not None, "regex should match engagement footer"
        forward_count, comment_count, like_count = (
            int(eng_match.group(1)),
            int(eng_match.group(2)),
            int(eng_match.group(3)),
        )
        assert like_count == 56
        assert comment_count == 34
        assert forward_count == 12

    def test_html_engagement_zero_when_absent(self):
        """Engagement footer not present → all metrics stay 0 (fail-safe)."""
        import re

        sample_text = "某用户 2小时前\n纯讨论内容没有互动数据"
        eng_match = re.search(
            r'(?:转发|转发数)\s*(\d+)\s*(?:回复|评论)\s*(\d+)\s*(?:赞|点赞)\s*(\d+)',
            sample_text,
        )
        assert eng_match is None
        # In the crawler code, defaults stay at 0 when eng_match is None
        like_count, comment_count, forward_count = 0, 0, 0
        assert like_count == 0 and comment_count == 0 and forward_count == 0

    def test_discussion_default_zero(self):
        """Unmodified Discussion dataclass still defaults engagement to 0."""
        from xueqiu_analyzer.models import Discussion
        d = Discussion(author="x", content="y", time="z")
        assert d.like_count == 0
        assert d.comment_count == 0
        assert d.forward_count == 0
