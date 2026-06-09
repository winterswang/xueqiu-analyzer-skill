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

    def test_list_kb(self):
        """list_knowledge_bases should return list with id/name."""
        from src.xueqiu_analyzer.ima_kb_uploader import list_knowledge_bases
        kbs = list_knowledge_bases()
        assert isinstance(kbs, list)
        if kbs:
            assert "id" in kbs[0]
            assert "name" in kbs[0]
