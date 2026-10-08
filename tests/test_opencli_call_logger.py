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


# ── 探针未命中 ≠ 失败 ──────────────────────────────────────────────────────
#
# 2026-10-05 实测：monitor 的 detail_fetcher 会按精确度顺序试 8 个正文选择器，
# 没命中就 continue，命中到 300 字才 break。两个页面各留 3 条 rc=2，台账于是
# 把 browser:extract 报成「75% 失败」—— 其实两次抓取都成功了，只是各探测了
# 3 次。假警报会淹掉真失败，所以调用方要能声明「这次未命中是预期的」。


def test_expect_miss_marks_probe_but_keeps_ok_faithful(tmp_path, monkeypatch):
    """ok 仍如实反映退出码，expect_miss 只多带一个解释标记。"""
    log_path = tmp_path / "calls.jsonl"
    monkeypatch.setenv("XUEQIU_OPENCLI_LOG", str(log_path))
    result = SimpleNamespace(returncode=2, stdout='{"error":"no match"}', stderr="")

    record_opencli_call(
        ["opencli", "browser", "detailfetch0", "extract", "--selector", "div.article"],
        started_at=0,
        result=result,
        caller="_opencli",
        expect_miss=True,
    )
    record = json.loads(log_path.read_text(encoding="utf-8"))

    assert record["ok"] is False        # 退出码没被改写
    assert record["returncode"] == 2
    assert record["expect_miss"] is True


def test_expect_miss_absent_by_default(tmp_path, monkeypatch):
    """不给标记时**不写这个字段** —— 台账要涨到 20MB 才轮转，别每行都加。"""
    log_path = tmp_path / "calls.jsonl"
    monkeypatch.setenv("XUEQIU_OPENCLI_LOG", str(log_path))
    result = SimpleNamespace(returncode=0, stdout="[]", stderr="")

    record_opencli_call(
        ["opencli", "xueqiu", "news", "PDD"], started_at=0, result=result, caller="unit"
    )
    record = json.loads(log_path.read_text(encoding="utf-8"))

    assert "expect_miss" not in record


def test_web_article_logs_command_name_as_operation(tmp_path, monkeypatch):
    """`web article` 的 operation 必须是**子命令名**（article），不是站点名（web）.

    回归（2026-10-08 实测）：首版只取了 args[0]，台账里全记成 "web"，而
    analyze_opencli_usage 的站点口径是按 operation 分类的 —— 于是这条主通道的
    站点请求全都不计入峰值，限速/风控监控会漏算。
    """
    log_path = tmp_path / "calls.jsonl"
    monkeypatch.setenv("XUEQIU_OPENCLI_LOG", str(log_path))
    result = SimpleNamespace(returncode=0, stdout="[]", stderr="")

    record_opencli_call(
        ["opencli", "web", "article", "https://xueqiu.com/1/2", "-f", "json"],
        started_at=0,
        result=result,
        caller="unit",
    )
    record = json.loads(log_path.read_text(encoding="utf-8"))

    assert record["operation"] == "article"
    assert record["target"] == "https://xueqiu.com/1/2"
