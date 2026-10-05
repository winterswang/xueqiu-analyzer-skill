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
