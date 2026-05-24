"""Tests for content quality checker (Layer 1 hard metrics)."""
import pytest
from src.xueqiu_analyzer.quality import (
    ContentQualityChecker,
    ContentQualityReport,
    _check_field,
    HEALTH_THRESHOLD,
)
from src.xueqiu_analyzer.models import (
    CrawlResult, News, Notice, Article, Discussion, FinancialData,
)


class TestContentQualityChecker:
    """ContentQualityChecker tests"""

    def test_empty_result(self):
        result = CrawlResult(symbol='TEST')
        checker = ContentQualityChecker()
        report = checker.check(result)
        assert report.news_count == 0
        assert report.health_score < HEALTH_THRESHOLD
        assert not report.is_healthy

    def test_all_news_have_content(self):
        result = CrawlResult(symbol='TEST')
        checker = ContentQualityChecker()
        ml = checker.min_content_len
        result.news = [
            News(title='t1', content='a' * ml, time=''),
            News(title='t2', content='b' * ml, time=''),
        ]
        checker = ContentQualityChecker()
        report = checker.check(result)
        assert report.news_count == 2
        assert report.news_with_content == 2
        assert report.news_ratio == 1.0

    def test_news_below_threshold(self):
        result = CrawlResult(symbol='TEST')
        checker = ContentQualityChecker()
        ml = checker.min_content_len
        result.news = [
            News(title='t1', content='a' * ml, time=''),
            News(title='t2', content='', time=''),    # empty
            News(title='t3', content='short', time=''),  # too short
        ]
        checker = ContentQualityChecker()
        report = checker.check(result)
        assert report.news_with_content == 1
        assert report.news_ratio == 1 / 3
        assert any('资讯有内容率' in a for a in report.alerts)

    def test_notices_have_content(self):
        result = CrawlResult(symbol='TEST')
        checker = ContentQualityChecker()
        ml = checker.min_content_len
        result.notices = [
            Notice(title='n1', content='Content ' * ml, link=''),
            Notice(title='n2', content='Body ' * ml, link=''),
        ]
        checker = ContentQualityChecker()
        report = checker.check(result)
        assert report.notice_count == 2
        assert report.notice_with_content == 2

    def test_articles_with_minimum_length(self):
        result = CrawlResult(symbol='TEST')
        result.articles = [
            Article(title='Long', author='A',
                    content='x' * 500, time=''),
            Article(title='Short', author='B',
                    content='x' * 50, time=''),  # < 200
        ]
        checker = ContentQualityChecker()
        report = checker.check(result)
        assert report.article_count == 2
        assert report.article_with_content == 1  # only the long one

    def test_no_articles_alerts(self):
        result = CrawlResult(symbol='TEST')
        checker = ContentQualityChecker()
        report = checker.check(result)
        assert any('无专栏文章' in a for a in report.alerts)

    def test_financial_data_complete(self):
        fd = FinancialData()
        fd.pe_ttm = 6.0
        fd.pb = 1.2
        fd.roe = 19.5
        fd.gross_margin = 89.6
        fd.net_margin = 59.5
        fd.revenue_growth = 15.0
        fd.profit_growth = 93.0

        result = CrawlResult(symbol='TEST', financial_data=fd)
        checker = ContentQualityChecker()
        report = checker.check(result)
        assert len(report.financial_fields_populated) == 7
        assert len(report.financial_fields_missing) == 0
        assert report.financial_completeness == 1.0

    def test_financial_data_partial(self):
        fd = FinancialData()
        fd.pe_ttm = 6.0
        fd.pb = 0.0  # genuinely missing (0 = no data)

        result = CrawlResult(symbol='TEST', financial_data=fd)
        checker = ContentQualityChecker()
        report = checker.check(result)
        assert 'PE(TTM)' in report.financial_fields_populated
        assert 'PB' in report.financial_fields_missing  # 0 counts as missing

    def test_financial_data_missing(self):
        result = CrawlResult(symbol='TEST', financial_data=None)
        checker = ContentQualityChecker()
        report = checker.check(result)
        assert any('财务数据完全缺失' in a for a in report.alerts)
        assert len(report.financial_fields_missing) == 7

    def test_health_score_full_data(self):
        """完整数据的健康分应 >= 90"""
        fd = FinancialData()
        for attr in ['pe_ttm', 'pb', 'roe', 'gross_margin',
                      'net_margin', 'revenue_growth', 'profit_growth']:
            setattr(fd, attr, 10.0)

        result = CrawlResult(symbol='TEST', financial_data=fd)
        result.news = [News(title='t', content='c' * 50, time='') for _ in range(9)]
        result.notices = [Notice(title='n', content='c' * 50, link='')
                          for _ in range(10)]
        result.articles = [Article(title='a', author='x',
                                    content='x' * 500, time='') for _ in range(7)]
        result.discussions = [Discussion(author='u', content='c' * 50, time='')
                              for _ in range(10)]

        checker = ContentQualityChecker()
        report = checker.check(result)
        assert report.health_score >= 90, f"Expected >=90, got {report.health_score}"
        assert report.is_healthy

    def test_health_score_empty(self):
        result = CrawlResult(symbol='TEST')
        checker = ContentQualityChecker()
        report = checker.check(result)
        assert report.health_score < 50

    def test_format_report(self):
        result = CrawlResult(symbol='TEST')
        result.news = [News(title='t', content='x' * 50, time='')]
        result.notices = [Notice(title='n', content='y' * 50, link='')]

        checker = ContentQualityChecker()
        report = checker.check(result)
        md = checker.format_report(report)

        assert '## ' in md
        assert '健康分' in md
        assert '资讯' in md
        assert '公告' in md

    def test_check_field_helper(self):
        report = ContentQualityReport()
        _check_field(report, 0, '标签')
        assert '标签' in report.financial_fields_missing

        report2 = ContentQualityReport()
        _check_field(report2, 10.0, '标签')
        assert '标签' in report2.financial_fields_populated

    def test_check_field_negative(self):
        """负值应视为有效数据（如亏损公司 ROE=-5%）"""
        report = ContentQualityReport()
        _check_field(report, -5.0, 'ROE')
        assert 'ROE' in report.financial_fields_populated

    def test_suggestions_when_unhealthy(self):
        result = CrawlResult(symbol='TEST')
        result.news = [News(title='t', content='', time='')]  # empty
        checker = ContentQualityChecker()
        report = checker.check(result)
        assert not report.is_healthy
        assert '新闻' in report.suggestions

    def test_article_suggestion_when_zero(self):
        result = CrawlResult(symbol='TEST')
        result.articles = []
        checker = ContentQualityChecker()
        report = checker.check(result)
        # Even if barely healthy or not, zero articles should trigger suggestion
        assert len(report.suggestions) > 0
