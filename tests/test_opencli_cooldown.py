"""熔断状态的读取与「被熔断拦下」的识别。

调用方要能回答两个问题，否则会被熔断器带偏：
  1. 现在是不是冷着？（0 秒的检查，别去白等 45 秒×N 的重试）
  2. 这次失败是不是熔断器干的？（`BROWSER_CONNECT` 有两个来源：熔断器刻意拦下、
     以及 daemon 真的没连上。前者不该重试、**更不该回退到不限速的直连路径**。）
"""

from __future__ import annotations

import json
import time

import pytest

from xueqiu_analyzer import opencli_cooldown as oc


@pytest.fixture()
def state_file(tmp_path, monkeypatch):
    path = tmp_path / "xueqiu-cooldown.json"
    monkeypatch.setenv("OPENCLI_COOLDOWN_STATE", str(path))
    return path


def test_no_state_file_means_no_cooldown(state_file):
    assert oc.cooldown_remaining_seconds() == 0.0
    assert oc.in_cooldown() is False


def test_future_until_means_in_cooldown(state_file):
    state_file.write_text(json.dumps({"until_ms": time.time() * 1000 + 3600_000}))

    assert oc.in_cooldown() is True
    assert 3500 < oc.cooldown_remaining_seconds() <= 3600


def test_past_until_means_expired(state_file):
    state_file.write_text(json.dumps({"until_ms": time.time() * 1000 - 1}))

    assert oc.in_cooldown() is False
    assert oc.cooldown_remaining_seconds() == 0.0


@pytest.mark.parametrize(
    "payload",
    ["", "not json", "[]", '{"until_ms": "abc"}', '{"until_ms": null}'],
)
def test_unreadable_state_is_treated_as_no_cooldown(state_file, payload):
    """读不出来一律当**没有冷却** —— 绝不能因为读不了状态就拦住正常调用。

    （与插件侧 `readState` 同一条纪律；那边的注释写着「绝不能因为读不了就拦住正常调用」。）
    """
    state_file.write_text(payload)

    assert oc.cooldown_remaining_seconds() == 0.0


def test_state_path_honours_env_override_and_expands_tilde(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENCLI_COOLDOWN_STATE", "~/xueqiu-cooldown.json")

    assert (
        oc.cooldown_path() == __import__("pathlib").Path.home() / "xueqiu-cooldown.json"
    )


def test_default_path_is_the_plugin_layout(monkeypatch):
    monkeypatch.delenv("OPENCLI_COOLDOWN_STATE", raising=False)

    assert (
        oc.cooldown_path()
        == __import__("pathlib").Path.home() / ".opencli" / "xueqiu-cooldown.json"
    )


def test_sentinel_separates_breaker_blocks_from_real_connection_failures():
    """两种 `BROWSER_CONNECT` 必须分得开。

    熔断器刻意拦下 → 别重试、别回退直连；daemon 真没连上 → 那是故障，可以按原逻辑处理。
    """
    blocked = 'Browser profile "__opencli_risk_cooldown__" is not connected'
    genuine = "Browser connect failed: daemon unreachable"

    assert oc.is_cooldown_failure(blocked) is True
    assert oc.is_cooldown_failure(genuine) is False
    assert oc.is_cooldown_failure(None, "", genuine) is False
    # stderr / error / 任意字段拼起来也要能认出来
    assert oc.is_cooldown_failure("stderr:", blocked, "exit=69") is True
