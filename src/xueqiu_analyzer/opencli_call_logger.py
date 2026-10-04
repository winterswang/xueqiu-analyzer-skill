"""Shared JSONL telemetry for Xueqiu opencli invocations."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_LOG_PATH = Path.home() / ".opencli" / "xueqiu-calls.jsonl"
MAX_LOG_BYTES = 20 * 1024 * 1024


def log_path() -> Path | None:
    """Return the active log path, or None when logging is disabled."""
    configured = os.environ.get("XUEQIU_OPENCLI_LOG", str(DEFAULT_LOG_PATH))
    if configured.lower() in {"", "off", "disabled"}:
        return None
    return Path(os.path.expanduser(configured))


def _operation(args: list[str]) -> str:
    """Extract a stable operation name from an opencli argv."""
    if not args:
        return "unknown"
    if args[0] == "opencli":
        args = args[1:]
    if args[0] == "xueqiu":
        return args[1] if len(args) > 1 else "xueqiu"
    if args[0] == "browser" and len(args) >= 3:
        return f"browser:{args[2]}"
    return args[0]


def _target(args: list[str]) -> str:
    """Extract the Xueqiu target without logging response content."""
    if not args:
        return ""
    if args[0] == "opencli":
        args = args[1:]
    if args[0] == "browser":
        if len(args) >= 4 and args[2] == "open":
            return args[3]
        return args[1] if len(args) > 1 else ""
    if args[0] != "xueqiu" or len(args) < 2:
        return ""

    command = args[1]
    if command in {"news", "comments", "stock", "stock-notices", "replies"}:
        return next((value for value in args[2:] if not value.startswith("-")), "")
    if command == "user-articles":
        try:
            return args[args.index("--user_id") + 1]
        except (ValueError, IndexError):
            return ""
    return ""


def default_source() -> str:
    """Infer a useful caller label when the environment does not provide one."""
    explicit = os.environ.get("XUEQIU_CALL_SOURCE", "")
    if explicit:
        return explicit
    entrypoint = Path(sys.argv[0]).name if sys.argv else "-"
    if entrypoint == "cli.py":
        return "xueqiu-monitor:pipeline"
    if entrypoint == "-":
        return "xueqiu-monitor:python-c"
    return f"xueqiu-analyzer:{entrypoint}"


def _trim(text: Any, limit: int = 2000) -> str:
    return str(text or "")[:limit]


def record_opencli_call(
    args: list[str],
    started_at: float,
    *,
    result: Any = None,
    error: BaseException | None = None,
    source: str | None = None,
    caller: str | None = None,
) -> None:
    """Append one completed opencli invocation as a single JSON line."""
    path = log_path()
    if path is None:
        return

    ended_at = datetime.now()
    started = datetime.fromtimestamp(started_at)
    returncode = getattr(result, "returncode", None)
    ok = error is None and returncode == 0
    error_text = str(getattr(error, "message", None) or error or "")
    if not error_text and returncode not in (0, None):
        error_text = str(getattr(result, "stderr", "") or "")
    command = [str(value) for value in args]
    record = {
        "schema": 1,
        "ts": ended_at.isoformat(timespec="milliseconds"),
        "local_date": ended_at.strftime("%Y-%m-%d"),
        "started_at": started.isoformat(timespec="milliseconds"),
        "duration_ms": round((ended_at.timestamp() - started_at) * 1000, 2),
        "source": source or default_source(),
        "caller": caller or "",
        "operation": _operation(command),
        "target": _target(command),
        "command": command,
        "ok": ok,
        "returncode": returncode,
        "error": _trim(error_text),
        "stdout_bytes": len(getattr(result, "stdout", "") or ""),
        "stderr_bytes": len(getattr(result, "stderr", "") or ""),
        "pid": os.getpid(),
        "ppid": os.getppid(),
    }

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > MAX_LOG_BYTES:
            rotated = path.with_suffix(path.suffix + ".1")
            rotated.write_bytes(path.read_bytes())
            path.write_text("", encoding="utf-8")
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    except OSError:
        # Telemetry must never break a crawl.
        pass
