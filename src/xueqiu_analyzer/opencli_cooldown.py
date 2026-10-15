"""读 opencli 插件层的**风控熔断**状态，并识别「被熔断拦下」的失败。

背景
----
`opencli-adapters/lib/cooldown.js` 命中站点风控后，会让该站点在冷却期内**发不出任何
请求**：它把 `OPENCLI_PROFILE` 指向一个不存在的 profile，命令于是在 routing 阶段硬
失败（`BROWSER_CONNECT` / exitCode 69）。调用方必须做两件事：

1. **别把它当故障** —— 不是 daemon 挂了，重试没有意义（每次还要白等约 45 秒的
   daemon 连接超时）。先读状态文件判断，那份检查是 **0 秒**的。
2. **绝不能因此回退到 Playwright / nodriver 直连** —— 那条路径不在插件管辖内、
   **不限速**。站点正因为被打而开了冷却，回退回去等于继续打它，而熔断器的全部意义
   就是停止这件事。

状态文件
--------
`~/.opencli/<域名键>-cooldown.json`（可用 `OPENCLI_COOLDOWN_STATE` 覆盖，与插件一致）::

    { "until_ms": <epoch ms>, "level": <int>, "reason": "<错误码>",
      "last_trip_ms": <epoch ms>, "trips": <int> }

域名键默认 `xueqiu`：插件的 `CANONICAL_DOMAIN_KEY` 把 `xueqiu.com` / `www.xueqiu.com`
/ `stock.xueqiu.com` 都映射回它，`web article` 打 xueqiu.com 时也归同一个键。

已知边界（**有意不覆盖**，都是 fail-open 方向）
---------------------------------------------
本模块只读**状态文件**与插件那两个**总刹车环境变量**，不重建插件的策略查找链：

- `~/.opencli/rate-limits.json` 里的 `sites.<键>.enabled: false`（站点级禁用）或
  `sites.<键>.cooldown.enabled: false` —— **不读**。在那种配置下插件不会拦，而这里
  仍可能报「冷着」⇒ 调用方会平白跳过抓取。要覆盖它就得在 Python 里重建
  `policyForCall`（domains → sites → 内置 → 通配）那条链，两份实现必然漂移，
  所以宁可不做、把事情写在这里。
- `sites.<键>.cooldown.state_path`（优先级**高于** `OPENCLI_COOLDOWN_STATE`）—— 同样不读。
  有人按插件 docstring 建议用 `state_path` 做隔离验证时，本模块会读老的默认路径、
  大概率读不到 ⇒ 返回「没有冷却」，预检静默失效（方向是 fail-open，不会误杀）。
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path

_PLUGIN_OFF_FOR_DISABLED = {"1", "true", "on", "yes", "enabled"}
_PLUGIN_NEGATIVE = {"0", "false", "off", "no", "disabled"}


def plugin_throttling_disabled() -> bool:
    """插件侧的总刹车是否被按下 —— 设了就**既不限速也不熔断**。

    对应 `lib/policy.js` 的 `applyEnv`：
    `OPENCLI_RATELIMIT_DISABLED`（真值 = 关）与 `XUEQIU_OPENCLI_THROTTLE`（负值 = 关）。

    不看这条，就会出现「状态文件里还有冷却、但插件已被关掉」时**报出假冷却** ——
    而消费方据此平白跳过抓取，还会把原因写成「站点在拦我们」。
    """
    if (os.environ.get("OPENCLI_RATELIMIT_DISABLED") or "").strip().lower() in (
        _PLUGIN_OFF_FOR_DISABLED
    ):
        return True
    return (os.environ.get("XUEQIU_OPENCLI_THROTTLE") or "").strip().lower() in (
        _PLUGIN_NEGATIVE
    )


# 熔断器拦下调用时用的**哨兵 profile 名**（`lib/cooldown.js` 的 BLOCK_PROFILE）。
# 它专用于这件事：不会与「daemon 真的没连上」（同样报 BROWSER_CONNECT）混同，
# 也不含「风控」二字、不会被 `waf.classify_failure` 误判成验证页。
COOLDOWN_SENTINEL = "__opencli_risk_cooldown__"

# 雪球在插件里的规范域名键（见模块 docstring）。
DEFAULT_SITE_KEY = "xueqiu"

DEFAULT_OPENCLI_DIR = Path.home() / ".opencli"


def _opencli_dir() -> Path:
    """插件状态目录。与插件的 `lib/paths.js` 一样，固定在家目录下。"""
    return DEFAULT_OPENCLI_DIR


def cooldown_path(site_key: str = DEFAULT_SITE_KEY) -> Path:
    """该站点的冷却状态文件路径（与插件 `cooldownPathFor` 同口径）。"""
    override = (os.environ.get("OPENCLI_COOLDOWN_STATE") or "").strip()
    if override:
        if override.startswith("~"):
            override = os.path.expanduser(override)
        return Path(override)
    return _opencli_dir() / f"{site_key}-cooldown.json"


def cooldown_remaining_seconds(
    site_key: str = DEFAULT_SITE_KEY, now_ms: float | None = None
) -> float:
    """冷却剩余秒数；不在冷却中（或读不到 / 状态损坏）返回 0。

    读不出来一律当**没有冷却** —— 与插件侧 `readState` 同一条纪律：绝不能因为
    读不了状态就拦住正常调用。
    """
    import time

    if plugin_throttling_disabled():
        return 0.0
    now = now_ms if now_ms is not None else time.time() * 1000
    try:
        state = json.loads(cooldown_path(site_key).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return 0.0
    if not isinstance(state, dict):
        return 0.0
    try:
        until = float(state.get("until_ms") or 0)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(until):
        # `1e309` 是合法 JSON 数字、`Infinity` 也能被解析出来 —— 不兜住的话剩余
        # 时间会变成 `inf`（永不解封）。插件侧 `Number()` 有同样性质，所以这不是
        # 口径漂移，只是别让调用方去打一份「剩余 inf 小时」的日志。
        return 0.0
    return max(0.0, (until - now) / 1000.0)


def in_cooldown(site_key: str = DEFAULT_SITE_KEY) -> bool:
    """该站点当前是否在熔断冷却中。"""
    return cooldown_remaining_seconds(site_key) > 0


def is_cooldown_failure(*parts: object) -> bool:
    """这些错误文本/字段里有没有熔断器留下的哨兵。

    用于把「熔断器刻意拦下」与「浏览器/daemon 真的连不上」（两者都报
    `BROWSER_CONNECT`）分开 —— 前者不该重试、更不该回退到不限速的直连路径。
    """
    text = " ".join(str(part) for part in parts if part)
    return COOLDOWN_SENTINEL in text
