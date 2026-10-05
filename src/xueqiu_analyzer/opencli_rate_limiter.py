"""Cross-process, randomized rate limiting for Xueqiu opencli commands."""

from __future__ import annotations

import fcntl
import json
import os
import random
import time
from pathlib import Path
from typing import Any


DEFAULT_STATE_PATH = Path.home() / ".opencli" / "xueqiu-throttle.json"

# 默认限速策略。这几个值是**策略决定**，不是实现细节：
#   - 命令起始时间之间随机间隔 6–12 秒（均值 9 秒）→ 单进程峰值上限 ≈ 6.7 次/分
#   - 每 30 次调用插一次 45–75 秒长停，打断"匀速机器"的形态
# 2026-10-05 由 12–24 秒收到 6–12 秒：证据显示被风控拦截那次是当天**第一次**
# 调用（此前 14 小时调用数为 0），即拦截并非即时频率所致；把爬取拖慢一倍
# 收益存疑。收到 6–12 秒后峰值上限 ~6.7 次/分，仍低于修复 browser open 限速
# 之前实测的 10 次/分。全部可用环境变量覆盖，无需改代码。
DEFAULT_MIN_DELAY_SECONDS = 6.0
DEFAULT_MAX_DELAY_SECONDS = 12.0
DEFAULT_LONG_PAUSE_EVERY = 30
DEFAULT_LONG_PAUSE_MIN_SECONDS = 45.0
DEFAULT_LONG_PAUSE_MAX_SECONDS = 75.0


def _env_float(name: str, default: float) -> float:
    try:
        return max(0.0, float(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return max(0, int(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


def throttle_enabled() -> bool:
    configured = os.environ.get("XUEQIU_OPENCLI_THROTTLE", "").lower()
    if configured in {"1", "true", "on", "enabled"}:
        return True
    if configured in {"0", "false", "off", "disabled"}:
        return False
    # Tests exercise mocked subprocess calls; requiring every unit test to opt
    # out would make otherwise-instant tests sleep for many minutes.
    return not bool(os.environ.get("PYTEST_CURRENT_TEST"))


def _should_throttle(args: list[str] | None) -> bool:
    """Only throttle commands that can initiate a Xueqiu site request."""
    if not args:
        return True
    values = [str(value) for value in args]
    if values and values[0] == "opencli":
        values = values[1:]
    if not values:
        return False
    if values[0] == "xueqiu":
        return "--help" not in values and "-h" not in values
    if values[0] == "browser":
        # 形态是 ["browser", <session>, <子命令>, ...]：
        #   browser open  → 导航到目标站点，**会发起雪球请求**，必须限速
        #   browser get/extract/close → 只跟已打开的本地标签页交互，不发请求
        # 2026-10-05 修：这里原写成 values[3]，而 values[3] 是 URL —— 拿 URL 和
        # "open" 比永远不成立，于是 browser open 从来没被限速过。当天实测：
        # 台账 130 次调用里 37 次是 browser:open，而限速器只记了 17 次
        # （只有 user-articles 被限速），限速覆盖约 13% 的流量。
        return len(values) >= 3 and values[2] == "open"
    return False


def _read_state(path: Path) -> dict[str, Any]:
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(state, dict):
            return state
    except (OSError, json.JSONDecodeError):
        pass
    return {"next_at": 0.0, "calls": 0}


def _write_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(state, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    temporary.replace(path)


def acquire_opencli_slot(
    source: str = "", args: list[str] | None = None
) -> dict[str, Any]:
    """Reserve the next Xueqiu command slot and sleep until it starts.

    The state file schedules command *start times* across processes. Locking is
    only held while reserving a slot; sleeping happens after release so one
    long browser command does not block unrelated crawls.
    """
    if not throttle_enabled() or not _should_throttle(args):
        return {"enabled": False, "waited_seconds": 0.0, "reserved_seconds": 0.0}

    state_path = Path(os.path.expanduser(
        os.environ.get("XUEQIU_OPENCLI_THROTTLE_STATE", str(DEFAULT_STATE_PATH))
    ))
    lock_path = state_path.with_suffix(state_path.suffix + ".lock")
    min_delay = _env_float("XUEQIU_OPENCLI_MIN_DELAY_SECONDS", DEFAULT_MIN_DELAY_SECONDS)
    max_delay = max(min_delay, _env_float("XUEQIU_OPENCLI_MAX_DELAY_SECONDS", DEFAULT_MAX_DELAY_SECONDS))
    long_every = _env_int("XUEQIU_OPENCLI_LONG_PAUSE_EVERY", DEFAULT_LONG_PAUSE_EVERY)
    long_min = _env_float("XUEQIU_OPENCLI_LONG_PAUSE_MIN_SECONDS", DEFAULT_LONG_PAUSE_MIN_SECONDS)
    long_max = max(long_min, _env_float("XUEQIU_OPENCLI_LONG_PAUSE_MAX_SECONDS", DEFAULT_LONG_PAUSE_MAX_SECONDS))

    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+", encoding="utf-8") as lock_handle:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
            state = _read_state(state_path)
            now = time.time()
            next_at = max(now, float(state.get("next_at", 0.0)))
            calls = int(state.get("calls", 0)) + 1
            interval = random.uniform(min_delay, max_delay)
            long_pause = 0.0
            if long_every and calls % long_every == 0:
                long_pause = random.uniform(long_min, long_max)
            reserved_seconds = interval + long_pause
            _write_state(state_path, {
                "next_at": next_at + reserved_seconds,
                "calls": calls,
                "last_source": source,
            })
            wait_seconds = max(0.0, next_at - now)
    except OSError:
        # A broken local lock/state file must not turn a data crawl into an
        # outage. The next invocation retries with fresh state.
        return {"enabled": True, "waited_seconds": 0.0, "reserved_seconds": 0.0}

    if wait_seconds:
        time.sleep(wait_seconds)
    return {
        "enabled": True,
        "waited_seconds": round(wait_seconds, 3),
        "reserved_seconds": round(reserved_seconds, 3),
        "long_pause": round(long_pause, 3),
    }
