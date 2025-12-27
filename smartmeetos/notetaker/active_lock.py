from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _lock_path() -> Path:
    return _repo_root() / ".secrets" / "active_meeting.json"


def _utc_now() -> dt.datetime:
    return dt.datetime.now(tz=dt.timezone.utc)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


@dataclass(frozen=True)
class ActiveMeetingLock:
    event_id: str
    event_start_utc: str
    expires_at_utc: str


def read_active_lock() -> ActiveMeetingLock | None:
    path = _lock_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None

    if not isinstance(data, dict):
        return None

    event_id = data.get("event_id")
    event_start_utc = data.get("event_start_utc")
    expires_at_utc = data.get("expires_at_utc")
    if not (isinstance(event_id, str) and isinstance(event_start_utc, str) and isinstance(expires_at_utc, str)):
        return None

    return ActiveMeetingLock(event_id=event_id, event_start_utc=event_start_utc, expires_at_utc=expires_at_utc)


def _parse_iso(iso: str) -> dt.datetime | None:
    try:
        parsed = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except Exception:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def lock_is_active(lock: ActiveMeetingLock) -> bool:
    expires = _parse_iso(lock.expires_at_utc)
    if expires is None:
        return False
    return _utc_now() < expires


def acquire_active_lock(*, event_id: str, event_start_utc: str, expires_at_utc: str) -> bool:
    """Enforce the 'only one meeting active at a time' policy.

    Uses a simple JSON lock file with an expiry. If the lock is stale, we overwrite it.
    """

    current = read_active_lock()
    if current and lock_is_active(current):
        return False

    _atomic_write_json(
        _lock_path(),
        {
            "event_id": event_id,
            "event_start_utc": event_start_utc,
            "expires_at_utc": expires_at_utc,
            "created_at_utc": _utc_now().isoformat(),
        },
    )
    return True


def release_active_lock(*, event_id: str, event_start_utc: str) -> None:
    path = _lock_path()
    current = read_active_lock()
    if not current:
        return

    # Only release if we still own the lock (defensive).
    if current.event_id != event_id or current.event_start_utc != event_start_utc:
        return

    try:
        path.unlink(missing_ok=True)
    except Exception:
        # Best-effort; expiry will eventually clear it.
        pass
