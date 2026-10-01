"""Regression tests for fetch_news_with_status.

Health gates must distinguish an actually empty news feed from a failed source.
The legacy fetch_news() intentionally returns [] on failure for fallback callers;
using it for health decisions hides total source failures.
"""

from types import SimpleNamespace

from xueqiu_analyzer import fetcher_opencli as fx


def _proc(rc=0, stdout="", stderr=""):
    return SimpleNamespace(returncode=rc, stdout=stdout, stderr=stderr)


def test_success_empty_is_not_error(monkeypatch):
    monkeypatch.setattr(fx, "_run", lambda *a, **k: _proc(stdout="[]"))
    rows, error = fx.fetch_news_with_status("600519.SH", 3)
    assert rows == []
    assert error is None


def test_command_failure_is_error_and_is_recorded(monkeypatch):
    recorded = []
    monkeypatch.setattr(
        fx, "_run",
        lambda *a, **k: _proc(rc=1, stderr="SECURITY_BLOCK: risk control"),
    )
    monkeypatch.setattr(fx, "record_source_failure", lambda *a, **k: recorded.append((a, k)))

    rows, error = fx.fetch_news_with_status("600519.SH", 3)

    assert rows == []
    assert "rc=1" in error
    assert "SECURITY_BLOCK" in error
    assert recorded and recorded[0][0][0] == "news"


def test_invalid_shape_is_error(monkeypatch):
    monkeypatch.setattr(fx, "_run", lambda *a, **k: _proc(stdout="{}"))
    rows, error = fx.fetch_news_with_status("600519.SH", 3)
    assert rows == []
    assert "expected list" in error


def test_legacy_fetch_news_preserves_empty_on_failure(monkeypatch):
    monkeypatch.setattr(
        fx, "_run",
        lambda *a, **k: _proc(rc=1, stderr="SECURITY_BLOCK: risk control"),
    )
    monkeypatch.setattr(fx, "record_source_failure", lambda *a, **k: None)
    assert fx.fetch_news("600519.SH", 3) == []

