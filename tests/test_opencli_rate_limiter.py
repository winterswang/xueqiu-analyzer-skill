from __future__ import annotations

import json

from xueqiu_analyzer import opencli_rate_limiter as limiter


def test_limiter_can_be_disabled(monkeypatch):
    monkeypatch.setenv("XUEQIU_OPENCLI_THROTTLE", "off")

    result = limiter.acquire_opencli_slot("test")

    assert result == {
        "enabled": False,
        "waited_seconds": 0.0,
        "reserved_seconds": 0.0,
    }


def test_limiter_reserves_cross_process_slots(tmp_path, monkeypatch):
    state = tmp_path / "throttle.json"
    monkeypatch.setenv("XUEQIU_OPENCLI_THROTTLE", "on")
    monkeypatch.setenv("XUEQIU_OPENCLI_THROTTLE_STATE", str(state))
    monkeypatch.setenv("XUEQIU_OPENCLI_MIN_DELAY_SECONDS", "2")
    monkeypatch.setenv("XUEQIU_OPENCLI_MAX_DELAY_SECONDS", "2")
    monkeypatch.setenv("XUEQIU_OPENCLI_LONG_PAUSE_EVERY", "2")
    monkeypatch.setenv("XUEQIU_OPENCLI_LONG_PAUSE_MIN_SECONDS", "1")
    monkeypatch.setenv("XUEQIU_OPENCLI_LONG_PAUSE_MAX_SECONDS", "1")
    monkeypatch.setattr(limiter.random, "uniform", lambda _min, _max: _max)
    sleeps = []
    monkeypatch.setattr(limiter.time, "sleep", sleeps.append)

    first = limiter.acquire_opencli_slot("first")
    second = limiter.acquire_opencli_slot("second")
    saved = json.loads(state.read_text())

    assert first["waited_seconds"] == 0.0
    assert first["reserved_seconds"] == 2.0
    assert second["waited_seconds"] > 0.0
    assert second["reserved_seconds"] == 3.0
    assert len(sleeps) == 1
    assert abs(sleeps[0] - second["waited_seconds"]) < 0.01
    assert saved["calls"] == 2
    assert saved["last_source"] == "second"


def test_local_browser_extract_and_help_do_not_wait(tmp_path, monkeypatch):
    monkeypatch.setenv("XUEQIU_OPENCLI_THROTTLE", "on")
    monkeypatch.setattr(limiter.time, "sleep", lambda _seconds: None)

    extract = limiter.acquire_opencli_slot(
        "extract",
        ["opencli", "browser", "detailfetch0", "extract", "--selector", "article"],
    )
    help_slot = limiter.acquire_opencli_slot(
        "help", ["opencli", "xueqiu", "user-articles", "--help"]
    )

    assert extract["enabled"] is False
    assert help_slot["enabled"] is False


def test_browser_open_is_throttled(tmp_path, monkeypatch):
    """browser open 会导航到目标站点、发起雪球请求，必须限速。

    回归（2026-10-05）：判定条件原先写成 `values[3] == "open"`，而
    `["opencli","browser",<session>,"open",<url>]` 去头后 values[3] 是 **URL**，
    拿 URL 和 "open" 比永远不成立 —— browser open 从未被限速。
    当天台账实测：130 次调用里 37 次是 browser:open，限速器只记了 17 次，
    覆盖约 13% 的流量，漏掉的恰恰是最重的页面导航。
    """
    monkeypatch.setenv("XUEQIU_OPENCLI_THROTTLE", "on")
    monkeypatch.setenv(
        "XUEQIU_OPENCLI_THROTTLE_STATE", str(tmp_path / "throttle.json")
    )
    monkeypatch.setattr(limiter.time, "sleep", lambda _seconds: None)

    slot = limiter.acquire_opencli_slot(
        "detail",
        ["opencli", "browser", "detailfetch0", "open", "https://xueqiu.com/1/2"],
    )

    assert slot["enabled"] is True


def test_should_throttle_covers_site_requests_only():
    """枚举式确认各类命令的判定，避免再出现「形态对不上、静默漏掉」。"""
    assert limiter._should_throttle(
        ["opencli", "browser", "s0", "open", "https://xueqiu.com/1/2"]
    ) is True
    assert limiter._should_throttle(
        ["opencli", "xueqiu", "user-articles", "--user_id", "1", "-f", "json"]
    ) is True
    # 本地操作：不发站点请求
    assert limiter._should_throttle(["opencli", "browser", "s0", "extract"]) is False
    assert limiter._should_throttle(["opencli", "browser", "s0", "get", "title"]) is False
    assert limiter._should_throttle(["opencli", "browser", "s0", "close"]) is False
    assert limiter._should_throttle(
        ["opencli", "xueqiu", "user-articles", "--help"]
    ) is False


# ── 默认策略 ──────────────────────────────────────────────────────────────


def test_default_interval_policy_is_pinned():
    """默认间隔是**策略决定**，不是实现细节。

    2026-10-05 由 12–24 秒收到 6–12 秒：证据显示被风控拦截那次是当天**第一次**
    调用（此前 14 小时调用数为 0），即拦截并非即时频率所致，把爬取拖慢一倍
    收益存疑。6–12 秒（均值 9 秒）的单进程峰值上限约 6.7 次/分，仍低于修复
    browser open 限速之前实测的 10 次/分。

    要再调这两个值 = 改策略，连同这条测试一起改即可。
    """
    assert limiter.DEFAULT_MIN_DELAY_SECONDS == 6.0
    assert limiter.DEFAULT_MAX_DELAY_SECONDS == 12.0
    assert 0 < limiter.DEFAULT_MIN_DELAY_SECONDS < limiter.DEFAULT_MAX_DELAY_SECONDS
    # 长停是"打断匀速机器形态"的机制，不能被关掉
    assert limiter.DEFAULT_LONG_PAUSE_EVERY > 0
    assert 0 < limiter.DEFAULT_LONG_PAUSE_MIN_SECONDS < limiter.DEFAULT_LONG_PAUSE_MAX_SECONDS


def test_default_band_used_when_env_absent(tmp_path, monkeypatch):
    """不设环境变量时，预定的间隔必须落在默认 band 内。"""
    monkeypatch.setenv("XUEQIU_OPENCLI_THROTTLE", "on")
    monkeypatch.setenv("XUEQIU_OPENCLI_THROTTLE_STATE", str(tmp_path / "t.json"))
    for name in ("XUEQIU_OPENCLI_MIN_DELAY_SECONDS", "XUEQIU_OPENCLI_MAX_DELAY_SECONDS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(limiter.time, "sleep", lambda _seconds: None)

    slot = limiter.acquire_opencli_slot("test")

    assert slot["enabled"] is True
    # 第一次调用不会触发长停，所以 reserved == 间隔本身
    assert (
        limiter.DEFAULT_MIN_DELAY_SECONDS
        <= slot["reserved_seconds"]
        <= limiter.DEFAULT_MAX_DELAY_SECONDS
    )
