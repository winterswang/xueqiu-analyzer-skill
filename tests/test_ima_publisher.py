"""
tests for ima_publisher — extract_title, prepend_report_title
"""

import pytest
from src.xueqiu_analyzer.ima_publisher import extract_title, prepend_report_title


class TestExtractTitle:
    def test_h1_heading(self):
        assert extract_title("# OKTA 投资报告") == "OKTA 投资报告"

    def test_h2_heading(self):
        assert extract_title("## 一、执行摘要") == "一、执行摘要"

    def test_h3_heading(self):
        assert extract_title("### 子章节") == "子章节"

    def test_leading_spaces(self):
        assert extract_title("   # 标题有空格") == "标题有空格"

    def test_skip_blockquote_then_heading(self):
        content = "> 免责声明：本报告...\n\n> 再一行引用\n\n## 一、执行摘要\n正文..."
        assert extract_title(content) == "一、执行摘要"

    def test_fallback_first_line(self):
        assert extract_title("没有井号的第一行") == "没有井号的第一行"

    def test_fallback_skip_blockquote(self):
        content = "> 引用行\n\n实际正文开始"
        assert extract_title(content) == "实际正文开始"

    def test_fallback_skip_empty_lines(self):
        content = "\n\n正文在这里\n..."
        assert extract_title(content) == "正文在这里"

    def test_fallback_truncate_long(self):
        long_line = "x" * 200
        assert extract_title(long_line) == long_line[:100]

    def test_empty_content(self):
        assert extract_title("") == "未命名报告"

    def test_only_blockquotes(self):
        assert extract_title("> 只有引用\n> 还是引用") == "未命名报告"


class TestPrependReportTitle:
    def test_with_stock_name(self):
        result = prepend_report_title("报告正文", "OKTA", "Okta(NASDAQ:OKTA)")
        assert result.startswith("# OKTA Okta(NASDAQ:OKTA) 投资分析报告\n\n")
        assert "报告正文" in result

    def test_without_stock_name(self):
        result = prepend_report_title("正文", "AAPL")
        assert result.startswith("# AAPL AAPL 投资分析报告\n\n")

    def test_preserves_content(self):
        content = "> 免责声明\n\n## 摘要\n正文"
        result = prepend_report_title(content, "TEST")
        assert content in result
        # content should appear after the title
        assert result.index(content) > 0
