from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class CalendarWatcherProcess:
    """Handle for a running calendar watcher process."""

    pid: int


def start_calendar_watcher(
    *,
    calendar_id: str = "primary",
    poll_seconds: int = 15,
    nylas_notetaker: bool = True,
    grant_id: str | None = None,
) -> CalendarWatcherProcess:
    """Start the existing working watcher (check_calendar.py) as a long-running process.

    This is the simplest reliable integration point for the larger project structure.
    If you later want this to run in-process (no subprocess), we can refactor
    `check_calendar.py` into a library entrypoint.
    """

    if nylas_notetaker and not grant_id:
        grant_id = os.environ.get("NYLAS_GRANT_ID")

    args = [sys.executable, "check_calendar.py", "--calendar", calendar_id, "--poll-seconds", str(poll_seconds)]
    if nylas_notetaker:
        args.append("--nylas-notetaker")
        if grant_id:
            args += ["--nylas-grant-id", grant_id]

    p = subprocess.Popen(args, cwd=os.getcwd())
    return CalendarWatcherProcess(pid=p.pid)
