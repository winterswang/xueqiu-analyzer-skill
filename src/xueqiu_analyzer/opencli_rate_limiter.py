"""Cross-process, randomized rate limiting for Xueqiu opencli commands.

**默认已关闭**（见 :func:`throttle_enabled`）：2026-10-11 起限速由 opencli 插件层
统一负责（``opencli-adapters/rate-limit.js`` 的 ``onBeforeExecute``
钩子），它覆盖所有调用方。本模块保留为逃生舱与策略参考。
"""

from __future__ import annotations

import fcntl
import json
import logging
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


# ⚠️ 曾用名 `XUEQIU_OPENCLI_THROTTLE` 是**插件层的刹车** —— 插件
# （`opencli-adapters/lib/policy.js` 的 `envFlagOff`）把 0/false/off/no/disabled
# 当关闭；而本模块把它当油门（1/true/on/enabled 才开）。**同一个变量名，两层极性相反**：
# 照旧文档设 `=1` 会同时打开两层（正是本模块要避免的双重限速），设 `=0` 则两层都关、
# 静默失去限速。故逃生舱改用插件层不认识的名字。
_THROTTLE_ENV = "XUEQIU_PY_THROTTLE"
_LEGACY_ENV = "XUEQIU_OPENCLI_THROTTLE"
_ENABLE_VALUES = {"1", "true", "on", "enabled"}
_warned_legacy_env = False


def throttle_enabled() -> bool:
    """本次进程内限速是否启用（默认关闭）。

    2026-10-11：限速能力已上移到 **opencli 插件层**
    （``opencli-adapters/rate-limit.js``，经 opencli 的 ``onBeforeExecute`` 钩子
    注册）。那一层覆盖**所有经 opencli registry 注册的命令**（``xueqiu/*``、
    ``web article``、``xiaohongshu/*``），本包与 crawler/monitor 的正常路径都走它。
    本模块若仍按老默认值生效，就会在每个调用上**再叠一层等待**（双重限速），
    故默认关闭，只保留为逃生舱。

    ⚠️ 但插件层**覆盖不到 ``opencli browser …`` 子命令**（不经钩子，上游
    jackwener/opencli#2606）。而 crawler / monitor 的回退路径
    （``opencli_extractor._attempt_via_browser``、``detail_fetcher._fetch_page_opencli_legacy``）
    用的正是它 —— 「插件不在位」与「需要本层兜底」是**同一件事**。所以插件缺失 /
    被停用 / discovery 失败时，必须设 ``XUEQIU_PY_THROTTLE=1``，否则那条回退路径
    完全不受限速。（2026-10-15 实测该路径当日 0 次调用，故为潜在风险而非现状。）

    策略常量与 ``_should_throttle`` 一并保留，供插件侧对照与回退。
    """
    global _warned_legacy_env
    if not _warned_legacy_env:
        legacy = os.environ.get(_LEGACY_ENV, "").lower()
        if legacy in _ENABLE_VALUES:
            _warned_legacy_env = True
            # 「大声说」而不是静默不生效：这个变量名是个陷阱（见上方注释）。
            logging.getLogger(__name__).warning(
                "%s 是**插件层**的开关，不会启用本 Python 层；要启用本层请设 %s=1"
                "（若你的本意是关掉插件层，那已经生效了）",
                _LEGACY_ENV,
                _THROTTLE_ENV,
            )
    return os.environ.get(_THROTTLE_ENV, "").lower() in _ENABLE_VALUES


def _should_throttle(args: list[str] | None) -> bool:
    """Only throttle commands that navigate to a real page (a site request).

    雪球请求是主要保护对象，但 `web article` 能指向任意域名（cninfo/hkexnews 等），
    所以判定按「是否真的发出导航」而不是按站点名。
    """
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
    if values[0] == "web":
        # 通用网页正文命令（opencli-adapters/article.js，承接原 browser
        # open/get/extract 三连）：func 里自己 page.goto 导航真实页面，与
        # browser open 同类，**必须限速**。之前它不在名单里，切过去就等于把
        # 正文抓取的限速整个拿掉 —— 比 10-05 那次漏掉 browser open 还严重。
        # 按**动词**匹配而不是整个站点，理由同上面的 browser 分支：将来 web 下
        # 出现不发请求的子命令时不该被一起限速（症状只是"变慢"，很难查）。
        # --help 是本地探测（is_article_available 用），不发请求，不限。
        if "--help" in values or "-h" in values:
            return False
        return len(values) >= 2 and values[1] == "article"
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

    state_path = Path(
        os.path.expanduser(
            os.environ.get("XUEQIU_OPENCLI_THROTTLE_STATE", str(DEFAULT_STATE_PATH))
        )
    )
    lock_path = state_path.with_suffix(state_path.suffix + ".lock")
    min_delay = _env_float(
        "XUEQIU_OPENCLI_MIN_DELAY_SECONDS", DEFAULT_MIN_DELAY_SECONDS
    )
    max_delay = max(
        min_delay,
        _env_float("XUEQIU_OPENCLI_MAX_DELAY_SECONDS", DEFAULT_MAX_DELAY_SECONDS),
    )
    long_every = _env_int("XUEQIU_OPENCLI_LONG_PAUSE_EVERY", DEFAULT_LONG_PAUSE_EVERY)
    long_min = _env_float(
        "XUEQIU_OPENCLI_LONG_PAUSE_MIN_SECONDS", DEFAULT_LONG_PAUSE_MIN_SECONDS
    )
    long_max = max(
        long_min,
        _env_float(
            "XUEQIU_OPENCLI_LONG_PAUSE_MAX_SECONDS", DEFAULT_LONG_PAUSE_MAX_SECONDS
        ),
    )

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
            _write_state(
                state_path,
                {
                    "next_at": next_at + reserved_seconds,
                    "calls": calls,
                    "last_source": source,
                },
            )
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
