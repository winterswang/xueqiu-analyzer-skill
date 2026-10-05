from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

from xueqiu_analyzer import fetcher_opencli
from xueqiu_analyzer.opencli_call_logger import record_opencli_call


def test_opencli_call_logger_records_safe_fields(tmp_path, monkeypatch):
    log_path = tmp_path / "calls.jsonl"
    monkeypatch.setenv("XUEQIU_OPENCLI_LOG", str(log_path))
    monkeypatch.setenv("XUEQIU_CALL_SOURCE", "test:cron")
    result = SimpleNamespace(returncode=0, stdout='[{"id":1}]', stderr="")

    record_opencli_call(
        ["opencli", "xueqiu", "news", "PDD", "--limit", "3"],
        started_at=0,
        result=result,
        caller="unit",
        throttle={"waited_seconds": 0.5, "reserved_seconds": 2.0},
    )
    record = json.loads(log_path.read_text(encoding="utf-8"))

    assert record["source"] == "test:cron"
    assert record["operation"] == "news"
    assert record["target"] == "PDD"
    assert record["ok"] is True
    assert record["stdout_bytes"] == len(result.stdout)
    assert "stdout" not in record
    assert record["throttle_wait_ms"] == 500.0
    assert record["throttle_reserved_ms"] == 2000.0


def test_fetcher_run_writes_one_jsonl_record(tmp_path, monkeypatch):
    log_path = tmp_path / "calls.jsonl"
    monkeypatch.setenv("XUEQIU_OPENCLI_LOG", str(log_path))
    monkeypatch.setenv("XUEQIU_CALL_SOURCE", "test:monitor-g1")

    def fake_run(*_args, **_kwargs):
        return subprocess.CompletedProcess(args=[], returncode=2, stdout="", stderr="blocked")

    monkeypatch.setattr(fetcher_opencli.subprocess, "run", fake_run)
    result = fetcher_opencli._run("xueqiu", "comments", "PDD", "--limit", "5")
    records = [json.loads(line) for line in log_path.read_text().splitlines()]

    assert result.returncode == 2
    assert len(records) == 1
    assert records[0]["source"] == "test:monitor-g1"
    assert records[0]["operation"] == "comments"
    assert records[0]["ok"] is False
    assert records[0]["error"] == "blocked"
