"""
tests for csv_exporter — export_csv, export_csv_from_json
"""

import json
import csv
import tempfile
from pathlib import Path

import pytest
from src.xueqiu_analyzer.models import CrawlResult, Discussion, News, Notice, Article
from src.xueqiu_analyzer.csv_exporter import export_csv, export_csv_from_json


def _make_sample_result():
    return CrawlResult(
        symbol="TEST",
        name="测试股票",
        discussions=[
            Discussion(author="张三", content="这是讨论内容1", time="2026-01-01",
                       comment_count=5, like_count=10, forward_count=2),
            Discussion(author="李四", content="这是讨论内容2", time="2026-01-02",
                       is_column=True, comment_count=0),
        ],
        news=[
            News(title="新闻1", content="新闻内容1", time="2026-01-01", source="财联社"),
            News(title="新闻2", content="新闻内容2", time="2026-01-02", source="雪球"),
        ],
        notices=[
            Notice(title="公告1", link="http://x.cn", time="2026-01-01",
                   notice_type="末期业绩", content="公告正文"),
        ],
        articles=[
            Article(title="文章1", author="王五", content="文章内容", time="2026-01-01",
                    comment_count=3, like_count=20, article_id="123"),
        ],
    )


class TestExportCsv:

    def test_export_all_types(self):
        result = _make_sample_result()
        with tempfile.TemporaryDirectory() as tmpdir:
            files = export_csv(result, tmpdir)

            assert len(files) == 4
            assert "discussions" in files
            assert "articles" in files
            assert "news" in files
            assert "notices" in files

            # Verify file existence and content
            for csv_type, path in files.items():
                assert Path(path).exists()
                assert Path(path).stat().st_size > 0

    def test_export_discussions_only(self):
        result = CrawlResult(
            symbol="TEST",
            discussions=[Discussion(author="test", content="c", time="2026")]
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            files = export_csv(result, tmpdir)
            assert len(files) == 1
            assert "discussions" in files

    def test_empty_data_raises(self):
        result = CrawlResult(symbol="EMPTY")
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(ValueError, match="没有数据"):
                export_csv(result, tmpdir)

    def test_custom_prefix(self):
        result = _make_sample_result()
        with tempfile.TemporaryDirectory() as tmpdir:
            files = export_csv(result, tmpdir, prefix="custom")
            path = files["discussions"]
            assert Path(path).name.startswith("custom_")

    def test_discussion_csv_columns(self):
        result = _make_sample_result()
        with tempfile.TemporaryDirectory() as tmpdir:
            files = export_csv(result, tmpdir)
            path = files["discussions"]
            with open(path, newline="", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                assert len(rows) == 2
                assert rows[0]["author"] == "张三"
                assert rows[0]["comment_count"] == "5"
                assert rows[0]["like_count"] == "10"
                assert rows[0]["forward_count"] == "2"
                assert rows[0]["is_column"] == "否"
                assert rows[1]["is_column"] == "是"

    def test_news_csv_columns(self):
        result = _make_sample_result()
        with tempfile.TemporaryDirectory() as tmpdir:
            files = export_csv(result, tmpdir)
            path = files["news"]
            with open(path, newline="", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                assert len(rows) == 2
                assert rows[0]["title"] == "新闻1"
                assert rows[0]["source"] == "财联社"

    def test_notices_csv_columns(self):
        result = _make_sample_result()
        with tempfile.TemporaryDirectory() as tmpdir:
            files = export_csv(result, tmpdir)
            path = files["notices"]
            with open(path, newline="", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                assert len(rows) == 1
                assert rows[0]["notice_type"] == "末期业绩"
                assert "pdf_link" in rows[0]

    def test_article_csv_columns(self):
        result = _make_sample_result()
        with tempfile.TemporaryDirectory() as tmpdir:
            files = export_csv(result, tmpdir)
            path = files["articles"]
            with open(path, newline="", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                assert len(rows) == 1
                assert rows[0]["title"] == "文章1"
                assert rows[0]["comment_count"] == "3"
                assert rows[0]["like_count"] == "20"
                assert rows[0]["article_id"] == "123"

    def test_utf8_bom(self):
        """CSV should start with UTF-8 BOM for Excel compatibility."""
        result = _make_sample_result()
        with tempfile.TemporaryDirectory() as tmpdir:
            files = export_csv(result, tmpdir)
            path = files["discussions"]
            raw = Path(path).read_bytes()
            assert raw[:3] == b"\xef\xbb\xbf"  # UTF-8 BOM


class TestExportCsvFromJson:

    def test_roundtrip(self):
        """Export → save JSON → load JSON → re-export → same data."""
        result = _make_sample_result()
        with tempfile.TemporaryDirectory() as tmpdir:
            # Save as JSON
            json_path = Path(tmpdir) / "test_data.json"
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(result.to_dict(), f, ensure_ascii=False, indent=2)

            # Re-export from JSON
            files = export_csv_from_json(str(json_path), tmpdir)
            assert len(files) == 4

            # Verify re-exported discussions have same data
            d_path = files["discussions"]
            with open(d_path, newline="", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                assert len(rows) == 2
                assert rows[0]["author"] == "张三"

    def test_missing_fields_default(self):
        """Models with missing optional fields should get default values."""
        minimal = CrawlResult(
            symbol="MIN",
            discussions=[Discussion(author="A", content="c", time="t")],
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            files = export_csv(minimal, tmpdir)
            path = files["discussions"]
            with open(path, newline="", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                row = next(reader)
                assert row["comment_count"] == "0"
                assert row["link"] == ""
