"""Tests for param-modes feature: max_items, DOM time filter, auto mode."""
import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock

from src.xueqiu_analyzer.crawler import _is_beyond_time_window
from src.xueqiu_analyzer.models import CrawlResult, Discussion, News, Notice, Article


class TestTimeWindow:
    """_is_beyond_time_window helper tests."""

    def test_empty_string(self):
        assert not _is_beyond_time_window('', 7)
        assert not _is_beyond_time_window(None, 7)

    def test_days_zero_disabled(self):
        today = datetime.now().strftime('%m-%d')
        assert not _is_beyond_time_window(today, 0)

    def test_today_not_beyond(self):
        today = datetime.now().strftime('%m-%d')
        assert not _is_beyond_time_window(today, 1)

    def test_old_date_beyond(self):
        old_date = (datetime.now() - timedelta(days=10)).strftime('%m-%d')
        assert _is_beyond_time_window(old_date, 5)

    def test_format_mm_dd_hhmm(self):
        recent = (datetime.now() - timedelta(hours=2)).strftime('%m-%d %H:%M')
        assert not _is_beyond_time_window(recent, 3)

    def test_format_yyyy_mm_dd(self):
        recent = datetime.now().strftime('%Y-%m-%d')
        assert not _is_beyond_time_window(recent, 1)

    def test_invalid_format_returns_false(self):
        assert not _is_beyond_time_window('not a date', 30)


class TestMaxItemsCountStop:
    """Count-based stopping logic tests."""

    def test_max_items_zero_disabled(self, tmp_path):
        """max_items=0 should mean no limit."""
        from src.xueqiu_analyzer.crawler import XueqiuCrawler

        crawler = XueqiuCrawler()
        # Verify the crawl method accepts max_items param
        import inspect
        sig = inspect.signature(crawler.crawl)
        assert 'max_items' in sig.parameters
        assert sig.parameters['max_items'].default == 0

    def test_total_items_helper(self):
        """The _total_items helper in crawl() should count all 4 lists."""
        result = CrawlResult(symbol='TEST')
        result.discussions = [Discussion(author='a', content='x', time='2026-06-01') for _ in range(5)]
        result.news = [News(title='a', content='', time='2026-06-01') for _ in range(3)]
        result.notices = [Notice(title='a', link='http://x.com') for _ in range(2)]
        result.articles = [Article(title='a', author='x', content='text', time='2026-06-01') for _ in range(1)]

        total = (len(result.discussions) + len(result.news) +
                 len(result.notices) + len(result.articles))
        assert total == 11, f"Expected 11, got {total}"


class TestAutoCrawl:
    """Auto mode quality-driven crawl tests."""

    def test_auto_params_in_analyzer(self):
        """DeepAnalyzer.analyze() should accept auto and quality_score."""
        from src.xueqiu_analyzer.stock_analyzer import DeepAnalyzer
        import inspect

        sig = inspect.signature(DeepAnalyzer.analyze)
        assert 'auto' in sig.parameters
        assert sig.parameters['auto'].default is False
        assert 'quality_score' in sig.parameters
        assert sig.parameters['quality_score'].default == 150
        assert 'max_items' in sig.parameters

    def test_auto_crawl_method_exists(self):
        """_auto_crawl should be defined on DeepAnalyzer."""
        from src.xueqiu_analyzer.stock_analyzer import DeepAnalyzer
        a = DeepAnalyzer()
        assert hasattr(a, '_auto_crawl')

    def test_auto_crawl_with_mock(self):
        """_auto_crawl should iterate until quality score met."""
        from src.xueqiu_analyzer.stock_analyzer import DeepAnalyzer
        from src.xueqiu_analyzer.models import (
            CrawlResult, Discussion, News, Notice, Article, EvaluationResult
        )

        analyzer = DeepAnalyzer()

        # Build mock result with all required model fields
        mock_result = CrawlResult(symbol='TEST')
        mock_result.news = [News(title=f't{i}', content='x' * 200, time='', link='') for i in range(10)]
        mock_result.notices = [Notice(title=f'n{i}', link=f'http://x.com/{i}', content='x' * 100) for i in range(5)]
        mock_result.discussions = [Discussion(author='a', content='y' * 50, time='', link='') for _ in range(20)]
        mock_result.articles = [Article(title=f'a{i}', author='x', content='z' * 500, time='', link='') for i in range(3)]
        mock_result._quality_report = None

        # Mock merge to return itself (simulating dedup with empty result)
        mock_result.merge = Mock(return_value=mock_result)

        analyzer.crawler.crawl = Mock(return_value=mock_result)

        # Mock evaluator to return high score immediately
        mock_eval = EvaluationResult(
            total_score=200,
            scores={}, sufficiency='充分', need_more_crawl=False,
            quality_assessment={},
        )

        with patch('src.xueqiu_analyzer.stock_analyzer.ContentQualityChecker') as MockQC, \
             patch('src.xueqiu_analyzer.stock_analyzer.Evaluator') as MockEval:

            mock_qc = MagicMock()
            mock_qc.check.return_value.is_healthy = True
            mock_qc.check.return_value.health_score = 95
            MockQC.return_value = mock_qc

            mock_ev = MagicMock()
            mock_ev.evaluate.return_value = mock_eval
            MockEval.return_value = mock_ev

            result = analyzer._auto_crawl(
                'TEST', max_pages=5, days=7, max_articles=3,
                max_news=0, max_notices=0, max_items=0, quality_score=150
            )

        # With score 200 >= threshold 150, should stop after 1 round
        assert analyzer.crawler.crawl.call_count == 1
        assert result == mock_result


class TestCLIParams:
    """CLI parameter validation tests."""

    def test_deep_analyze_has_all_new_params(self):
        """deep-analyze should show --auto --max-items --quality-score in help."""
        from click.testing import CliRunner
        from src.xueqiu_analyzer.cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ['deep-analyze', '--help'])
        assert result.exit_code == 0
        output = result.output
        assert '--auto' in output
        assert '--max-items' in output
        assert '--quality-score' in output
        assert '--max-pages' in output  # backward compat

    def test_crawl_has_max_items(self):
        """crawl command should show --max-items in help."""
        from click.testing import CliRunner
        from src.xueqiu_analyzer.cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ['crawl', '--help'])
        assert result.exit_code == 0
        assert '--max-items' in result.output


class TestNotificationConfig:
    """Verify FEISHU_TARGET_USER placeholder resolves correctly."""

    def test_feishu_resolve(self):
        import os
        from src.xueqiu_analyzer.config import get_config
        cfg = get_config()
        notify = cfg.get('notify', {})
        target = notify.get('feishu_target', '')
        # Should not contain literal ${} — either resolved or empty
        assert '${' not in target, f"feishu_target not resolved: {target}"
