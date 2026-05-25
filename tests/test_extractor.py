"""
测试 ScrapingExtractor

运行方式：
    PYTHONPATH=src pytest tests/test_extractor.py -v
"""

import json
import time
import pytest
from unittest.mock import patch, MagicMock
from xueqiu_analyzer.extractor import (
    ArticleContent,
    ScrapingExtractor,
    call_deepseek_extract,
    fetch_page_html,
    _clean_html,
)


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_html():
    return """
    <html>
    <body>
        <article>
            <h1>贵州茅台2024年度财报分析</h1>
            <div class="author">张三</div>
            <div class="time">2024-03-28 10:00</div>
            <div class="content">
                <p>贵州茅台今日发布2024年度财报，实现营业收入1476亿元，同比增长19%。</p>
                <p>公司净利润达747亿元，同比增长18%。</p>
                <p>分析师认为茅台的护城河依然稳固。</p>
            </div>
        </article>
    </body>
    </html>
    """


# ── ArticleContent 单元测试 ─────────────────────────────────────────────────

class TestArticleContent:
    def test_is_valid_with_valid_content(self):
        article = ArticleContent(
            title="测试",
            author="作者",
            content="这是一段有效的正文内容，长度超过50个字符。" * 5,
            time="2024-01-01",
            symbols='["600519"]',
            url="https://xueqiu.com/123/456"
        )
        assert article.is_valid() is True

    def test_is_valid_with_short_content(self):
        article = ArticleContent(content="太短", url="https://xueqiu.com/123/456")
        assert article.is_valid() is False

    def test_is_valid_with_empty_content(self):
        article = ArticleContent(url="https://xueqiu.com/123/456")
        assert article.is_valid() is False

    def test_to_dict(self):
        article = ArticleContent(title="测试", content="正文内容" * 20)
        d = article.to_dict()
        assert isinstance(d, dict)
        assert d["title"] == "测试"


# ── call_deepseek_extract 测试 ──────────────────────────────────────────────

class TestCallDeepSeekExtract:
    def _make_mock_response(self, content_str: str):
        """返回一个 mock，read() 返回 content_str（str 类型）的 UTF-8 编码"""
        mock_resp = MagicMock()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read = MagicMock(return_value=content_str.encode("utf-8"))
        return mock_resp

    def test_basic_extraction(self):
        response_data = {
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "title": "贵州茅台2024年度财报分析",
                        "author": "张三",
                        "content": "贵州茅台今日发布2024年度财报，实现营业收入1476亿元，同比增长19%。\n公司净利润达747亿元，同比增长18%。",
                        "time": "2024-03-28 10:00",
                        "symbols": ["600519"],
                    }, ensure_ascii=False)
                }
            }]
        }
        with patch("xueqiu_analyzer.extractor.urllib.request.urlopen",
                  return_value=self._make_mock_response(json.dumps(response_data))):
            result = call_deepseek_extract("<html>测试</html>", "https://xueqiu.com/123/456")

        assert result.title == "贵州茅台2024年度财报分析"
        assert result.author == "张三"
        assert len(result.content) >= 50
        assert "600519" in result.symbols
        assert result.url == "https://xueqiu.com/123/456"

    def test_api_failure_returns_url(self):
        mock_resp = MagicMock()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.side_effect = Exception("Network error")

        with patch("xueqiu_analyzer.extractor.urllib.request.urlopen", return_value=mock_resp):
            result = call_deepseek_extract("<html>test</html>", "https://xueqiu.com/123/456")

        assert result.url == "https://xueqiu.com/123/456"

    def test_json_in_code_block(self):
        inner = json.dumps({
            "title": "贵州茅台2024年度财报分析",
            "author": "张三",
            "content": "贵州茅台今日发布2024年度财报，实现营业收入1476亿元，同比增长19%。",
            "time": "2024-03-28 10:00",
            "symbols": ["600519"],
        }, ensure_ascii=False)
        raw = inner

        response_data = {"choices": [{"message": {"content": raw}}]}
        with patch("xueqiu_analyzer.extractor.urllib.request.urlopen",
                  return_value=self._make_mock_response(json.dumps(response_data))):
            result = call_deepseek_extract("<html>test</html>", "https://xueqiu.com/123/456")

        assert result.title == "贵州茅台2024年度财报分析"


# ── fetch_page_html 测试 ──────────────────────────────────────────────────────

class TestFetchPageHtml:
    def test_clean_html_removes_scripts(self):
        dirty = """
        <script>alert('xss')</script>
        <nav>导航</nav>
        <style>.red { color: red }</style>
        <p>正文内容</p>
        <footer>页脚</footer>
        """
        clean = _clean_html(dirty)
        assert "alert" not in clean
        assert "导航" not in clean
        assert "red" not in clean
        assert "正文内容" in clean


# ── ScrapingExtractor 测试 ─────────────────────────────────────────────────
#
# 注意：pytest @patch 装饰器 bottom-up 应用顺序：
#   @patch("fetch_page_html")        outer → 第1参数
#   @patch("call_deepseek_extract")  inner → 第2参数
# 因此：param[0] = call_deepseek_extract mock，param[1] = fetch_page_html mock
#

class TestScrapingExtractor:
    @patch("xueqiu_analyzer.extractor.fetch_page_html")
    @patch("xueqiu_analyzer.extractor.call_deepseek_extract")
    def test_extract_success(self, mock_call_deepseek, mock_fetch_page, sample_html):
        # param[0]=call_deepseek_extract mock → 模拟 DeepSeek LLM 返回
        mock_call_deepseek.return_value = ArticleContent(
            title="贵州茅台2024年度财报分析",
            author="张三",
            content="贵州茅台今日发布2024年度财报，实现营业收入1476亿元，同比增长19%。\n公司净利润达747亿元，同比增长18%。",
            time="2024-03-28 10:00",
            symbols='["600519"]',
            url="https://xueqiu.com/123/456"
        )
        # param[1]=fetch_page_html mock → 模拟 Playwright 返回 HTML
        mock_fetch_page.return_value = sample_html

        extractor = ScrapingExtractor()
        result = extractor.extract("https://xueqiu.com/123/456")

        assert result.title == "贵州茅台2024年度财报分析"
        assert result.is_valid() is True
        mock_fetch_page.assert_called_once()
        mock_call_deepseek.assert_called_once()

    @patch("xueqiu_analyzer.extractor.fetch_page_html")
    @patch("xueqiu_analyzer.extractor.call_deepseek_extract")
    def test_extract_fallback_on_failure(self, mock_call_deepseek, mock_fetch_page):
        mock_fetch_page.return_value = ""
        mock_call_deepseek.side_effect = Exception("API Error")

        extractor = ScrapingExtractor()
        result = extractor.extract("https://xueqiu.com/123/456")

        assert result.url == "https://xueqiu.com/123/456"

    @patch("xueqiu_analyzer.extractor.fetch_page_html")
    @patch("xueqiu_analyzer.extractor.call_deepseek_extract")
    def test_extract_invalid_result_uses_fallback(self, mock_call_deepseek, mock_fetch_page):
        mock_fetch_page.return_value = "<html>内容</html>"
        mock_call_deepseek.return_value = ArticleContent(content="太短", url="https://xueqiu.com/123/456")

        extractor = ScrapingExtractor()
        result = extractor.extract("https://xueqiu.com/123/456")

        assert result.url == "https://xueqiu.com/123/456"


# ── 性能测试 ────────────────────────────────────────────────────────────────

class TestPerformance:
    @patch("xueqiu_analyzer.extractor.fetch_page_html")
    @patch("xueqiu_analyzer.extractor.call_deepseek_extract")
    def test_extract_time_budget(self, mock_call_deepseek, mock_fetch_page):
        """
        param[0]=call_deepseek_extract mock → 模拟 LLM 返回 ArticleContent
        param[1]=fetch_page_html mock → 模拟 Playwright 返回 HTML
        """
        mock_call_deepseek.return_value = ArticleContent(
            content="这是一段有效的正文内容，长度超过50个字符。" * 5,
            url="https://xueqiu.com/123/456"
        )
        mock_fetch_page.return_value = "<html><body><article><p>正正文内容正正文内容正正文内容正正文内容正正文内容正正文内容正正文内容正正文内容正正文内容正正文内容正正文内容正正文内容正正文内容正正文内容正正文内容正正文内容正正文内容正正文内容正正文内容正正文内容正正文内容正正文内容正正文内容正正文内容正正文内容正正文内容正正文内容正正文内容正正文内容正正文内容</p></article></body></html>"

        extractor = ScrapingExtractor()
        start = time.time()
        result = extractor.extract("https://xueqiu.com/123/456")
        elapsed = time.time() - start

        assert result.is_valid(), f"提取失败，content={result.content!r}"
        assert elapsed < 30, f"提取耗时 {elapsed:.1f}s，超过 30s 限制"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])