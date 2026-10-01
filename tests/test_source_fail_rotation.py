"""Tests for source_failures.jsonl 天级轮转（fetcher_opencli）。

轮转必须只发生在跨天时 —— 同一天内不能动文件，否则 monitor 的 health_check
会读不到当天的早期失败，重新变成「静默无失败」。
"""

import json
import os
from datetime import date, datetime, timedelta

from xueqiu_analyzer import fetcher_opencli as fx


# ── helpers ─────────────────────────────────────────────────

def _log_path(tmp_path):
    return str(tmp_path / "logs" / "source_failures.jsonl")


def _write(path, recs):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for rec in recs:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _set_mtime(path, when):
    ts = datetime(when.year, when.month, when.day, 12, 0, 0).timestamp()
    os.utime(path, (ts, ts))


def _archive_path(tmp_path, when):
    return tmp_path / "logs" / "source_failures" / ("%s.jsonl" % when.isoformat())


# ── _rotate_fail_log ────────────────────────────────────────

def test_same_day_does_not_touch_file(tmp_path):
    log = _log_path(tmp_path)
    _write(log, [{"ts": "x", "source": "news"}])
    _set_mtime(log, date.today())

    assert fx._rotate_fail_log(log) is None
    assert os.path.exists(log)
    assert not (tmp_path / "logs" / "source_failures").exists()


def test_cross_day_archives_previous_day(tmp_path):
    log = _log_path(tmp_path)
    yesterday = date.today() - timedelta(days=1)
    _write(log, [{"ts": "%sT10:00:00" % yesterday.isoformat(), "source": "news"}])
    _set_mtime(log, yesterday)

    dest = fx._rotate_fail_log(log)

    assert dest == str(_archive_path(tmp_path, yesterday))
    archived = _archive_path(tmp_path, yesterday)
    assert archived.exists()
    assert json.loads(archived.read_text(encoding="utf-8").splitlines()[0])["source"] == "news"
    assert not os.path.exists(log)


def test_empty_file_is_left_alone(tmp_path):
    log = _log_path(tmp_path)
    os.makedirs(os.path.dirname(log), exist_ok=True)
    open(log, "w").close()
    _set_mtime(log, date.today() - timedelta(days=3))

    assert fx._rotate_fail_log(log) is None
    assert os.path.exists(log)


def test_missing_file_is_noop(tmp_path):
    assert fx._rotate_fail_log(_log_path(tmp_path)) is None


def test_prunes_archives_older_than_keep_days(tmp_path):
    log = _log_path(tmp_path)
    yesterday = date.today() - timedelta(days=1)
    _write(log, [{"ts": "x"}])
    _set_mtime(log, yesterday)

    archive_dir = tmp_path / "logs" / "source_failures"
    archive_dir.mkdir(parents=True)
    old = archive_dir / ("%s.jsonl" % (date.today() - timedelta(days=100)).isoformat())
    recent = archive_dir / ("%s.jsonl" % (date.today() - timedelta(days=5)).isoformat())
    old.write_text("{}\n", encoding="utf-8")
    recent.write_text("{}\n", encoding="utf-8")

    fx._rotate_fail_log(log, keep_days=30)

    assert not old.exists()
    assert recent.exists()
    assert _archive_path(tmp_path, yesterday).exists()


# ── record_source_failure ───────────────────────────────────

def test_record_appends_within_same_day(tmp_path, monkeypatch):
    log = _log_path(tmp_path)
    monkeypatch.setattr(fx, "FAIL_LOG", log)

    fx.record_source_failure("news", "SH600519", 1, "风控验证页")
    fx.record_source_failure("notices", "SH600519", 1, "接口异常")

    lines = open(log, encoding="utf-8").read().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["reason"] == "风控验证页"
    assert not (tmp_path / "logs" / "source_failures").exists()


def test_record_rotates_across_days(tmp_path, monkeypatch):
    log = _log_path(tmp_path)
    yesterday = date.today() - timedelta(days=1)
    _write(log, [{"ts": "%sT10:00:00" % yesterday.isoformat(), "source": "news"}])
    _set_mtime(log, yesterday)
    monkeypatch.setattr(fx, "FAIL_LOG", log)

    fx.record_source_failure("news", "SH600519", 1, "风控验证页")

    # 新文件只含今天这一条 —— 读取方按固定路径读，拿到的就是「今天」
    lines = open(log, encoding="utf-8").read().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["ts"].startswith(date.today().isoformat())
    # 昨天的记录完整进了归档，没有丢
    archived = _archive_path(tmp_path, yesterday)
    assert archived.exists()
    assert json.loads(archived.read_text(encoding="utf-8").splitlines()[0])["source"] == "news"
