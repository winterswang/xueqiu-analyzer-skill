"""
tests for ima_kb_uploader — file detection, API error handling
"""

from pathlib import Path

import pytest
from src.xueqiu_analyzer.ima_kb_uploader import (
    _detect_media_type,
    upload_file,
    upload_csv_set,
)


class TestDetectMediaType:

    def test_csv(self):
        mt, ct = _detect_media_type("data.csv")
        assert mt == 5
        assert ct == "text/csv"

    def test_pdf(self):
        mt, ct = _detect_media_type("report.pdf")
        assert mt == 1
        assert ct == "application/pdf"

    def test_xlsx(self):
        mt, ct = _detect_media_type("data.xlsx")
        assert mt == 5
        assert "spreadsheet" in ct

    def test_txt(self):
        mt, ct = _detect_media_type("notes.txt")
        assert mt == 13
        assert ct == "text/plain"

    def test_docx(self):
        mt, ct = _detect_media_type("doc.docx")
        assert mt == 3

    def test_unknown_fallback(self):
        mt, ct = _detect_media_type("file.xyz")
        assert mt == 5  # fallback
        assert ct == "application/octet-stream"

    def test_no_extension(self):
        mt, ct = _detect_media_type("README")
        assert mt == 5  # fallback
        assert ct == "application/octet-stream"

    def test_uppercase_extension(self):
        mt, ct = _detect_media_type("DATA.CSV")
        assert mt == 5
        assert ct == "text/csv"

    def test_html_uses_type20_text_html(self):
        # 2026-07-21: HTML must use media_type=20 + content_type='text/html'
        # so IMA backend parses HTML structure and indexes for search.
        # Earlier combinations (type=13 + text/plain, or type=13 + text/html)
        # succeed at create_media API but the record is never indexed —
        # search_knowledge returns 0 hits.
        # Source of truth: /root/code/openclaw-workspace/skills/ima/
        #   knowledge-base/scripts/preflight-check.cjs
        # (which matches what IMA UI does).
        mt, ct = _detect_media_type("report.html")
        assert mt == 20
        assert ct == "text/html"

    def test_htm_uses_type20_text_html(self):
        mt, ct = _detect_media_type("page.htm")
        assert mt == 20
        assert ct == "text/html"

    def test_html_uppercase(self):
        # .HTML extension must also resolve to type=20 / text/html
        mt, ct = _detect_media_type("INDEX.HTML")
        assert mt == 20
        assert ct == "text/html"


class TestUploadFileEdgeCases:

    def test_nonexistent_file(self):
        with pytest.raises(FileNotFoundError):
            upload_file("/nonexistent/path.csv", "KB123")

    def test_empty_file(self, tmp_path):
        p = tmp_path / "empty.csv"
        p.write_text("")
        with pytest.raises(ValueError, match="空文件"):
            upload_file(str(p), "KB123")

    def test_csv_too_large(self, tmp_path, monkeypatch):
        # Override MAX_CSV_SIZE to a small value for testing
        import src.xueqiu_analyzer.ima_kb_uploader as mod
        monkeypatch.setattr(mod, "MAX_CSV_SIZE", 10)  # 10 bytes
        p = tmp_path / "large.csv"
        p.write_text("a" * 100)
        with pytest.raises(ValueError, match="过大"):
            upload_file(str(p), "KB123")

    def test_missing_credentials(self, monkeypatch):
        """Should raise error when IMA credentials are not configured."""
        import src.xueqiu_analyzer.ima_kb_uploader as mod
        monkeypatch.setattr(mod, "_get_ima_credentials", lambda: ("", ""))
        p = Path("/tmp/test_upload.csv")
        if p.exists():
            p.unlink()
        p.write_text("col1,col2\nv1,v2")
        with pytest.raises(RuntimeError, match="凭证"):
            upload_file(str(p), "KB123")


class TestUploadCsvSet:

    def test_empty_input(self):
        result = upload_csv_set({}, "KB123")
        assert result == {"success": [], "failed": {}}

    def test_missing_files_returned_in_failed(self):
        """Missing files should appear in failed dict (not raise)."""
        csv_files = {"discussions": "/nonexistent/d.csv"}
        result = upload_csv_set(csv_files, "KB123")
        assert result["success"] == []
        assert "discussions" in result["failed"]

    def test_list_kb(self, monkeypatch):
        """list_knowledge_bases parses the payload into id/name pairs.

        This used to call the live IMA OpenAPI: it only ever passed on machines
        with ~/.config/ima/ credentials present, and failed in CI. Mocking _api
        turns it into an actual unit test of the parsing logic.
        """
        import src.xueqiu_analyzer.ima_kb_uploader as mod
        monkeypatch.setattr(mod, "_api", lambda path, body: {
            "code": 0,
            "data": {
                "addable_knowledge_base_list": [
                    {"id": "KB1", "name": "研报库"},
                    {"id": "KB2", "name": "笔记库"},
                ],
                "is_end": True,
            },
        })

        assert mod.list_knowledge_bases() == [
            {"id": "KB1", "name": "研报库"},
            {"id": "KB2", "name": "笔记库"},
        ]

    def test_list_kb_paginates_until_is_end(self, monkeypatch):
        """Pagination must follow next_cursor until is_end."""
        import src.xueqiu_analyzer.ima_kb_uploader as mod
        pages = [
            {"code": 0, "data": {"addable_knowledge_base_list": [{"id": "KB1", "name": "a"}],
                                 "is_end": False, "next_cursor": "c1"}},
            {"code": 0, "data": {"addable_knowledge_base_list": [{"id": "KB2", "name": "b"}],
                                 "is_end": True}},
        ]
        calls = []

        def fake_api(path, body):
            calls.append(body)
            return pages[len(calls) - 1]

        monkeypatch.setattr(mod, "_api", fake_api)

        assert mod.list_knowledge_bases() == [
            {"id": "KB1", "name": "a"},
            {"id": "KB2", "name": "b"},
        ]
        assert calls == [{"cursor": "", "limit": 50}, {"cursor": "c1", "limit": 50}]

    def test_list_kb_raises_on_api_error(self, monkeypatch):
        """Non-zero code must raise rather than silently return an empty list."""
        import src.xueqiu_analyzer.ima_kb_uploader as mod
        monkeypatch.setattr(
            mod, "_api", lambda path, body: {"code": 110021, "message": "rate limited"}
        )

        with pytest.raises(RuntimeError, match="获取知识库列表失败"):
            mod.list_knowledge_bases()
