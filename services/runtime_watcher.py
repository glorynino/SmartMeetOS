from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _secrets_dir() -> Path:
    return _repo_root() / ".secrets"


def _pid_path() -> Path:
    return _secrets_dir() / "calendar_watcher.pid.json"


@dataclass(frozen=True)
class WatcherStatus:
    running: bool
    pid: int | None


def _process_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        # Signal 0 does not kill; it only checks existence.
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def get_watcher_status() -> WatcherStatus:
    path = _pid_path()
    if not path.exists():
        return WatcherStatus(running=False, pid=None)

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return WatcherStatus(running=False, pid=None)

    pid = data.get("pid")
    if not isinstance(pid, int):
        return WatcherStatus(running=False, pid=None)

    if _process_exists(pid):
        return WatcherStatus(running=True, pid=pid)

    # Stale pid file.
    try:
        path.unlink(missing_ok=True)
    except Exception:
        pass

    return WatcherStatus(running=False, pid=None)


def start_watcher(
    *,
    calendar_id: str = "primary",
    poll_seconds: int = 15,
    nylas_notetaker: bool = True,
    grant_id: str | None = None,
) -> WatcherStatus:
    current = get_watcher_status()
    if current.running:
        return current

    if nylas_notetaker and not grant_id:
        grant_id = os.environ.get("NYLAS_GRANT_ID")

    args = [
        sys.executable,
        "check_calendar.py",
        "--calendar",
        calendar_id,
        "--poll-seconds",
        str(int(poll_seconds)),
    ]
    if nylas_notetaker:
        args.append("--nylas-notetaker")
        if grant_id:
            args += ["--nylas-grant-id", grant_id]

    p = subprocess.Popen(args, cwd=str(_repo_root()))

    _secrets_dir().mkdir(parents=True, exist_ok=True)
    _pid_path().write_text(json.dumps({"pid": p.pid}, indent=2), encoding="utf-8")

    return WatcherStatus(running=True, pid=p.pid)


def stop_watcher() -> WatcherStatus:
    st = get_watcher_status()
    if not st.running or not st.pid:
        return WatcherStatus(running=False, pid=None)

    pid = st.pid
    try:
        # Try graceful first.
        os.kill(pid, signal.SIGTERM)
    except Exception:
        pass

    # If still alive, try harder.
    if _process_exists(pid):
        try:
            os.kill(pid, signal.SIGKILL)
        except Exception:
            pass

    try:
        _pid_path().unlink(missing_ok=True)
    except Exception:
        pass

    return WatcherStatus(running=False, pid=None)
