from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class FailureCode(str, Enum):
    # Join/entry
    JOIN_TIMEOUT = "JOIN_TIMEOUT"
    WAITING_ROOM_TIMEOUT = "WAITING_ROOM_TIMEOUT"

    # Runtime
    DISCONNECTED_TIMEOUT = "DISCONNECTED_TIMEOUT"
    BOT_REMOVED = "BOT_REMOVED"
    MAX_DURATION_EXCEEDED = "MAX_DURATION_EXCEEDED"

    # Admission/host denial
    JOIN_REFUSED_MAX = "JOIN_REFUSED_MAX"

    # Runtime limits
    KICKED_MAX = "KICKED_MAX"

    # Scheduler
    SKIPPED_OVERLAP_CONFLICT = "SKIPPED_OVERLAP_CONFLICT"

    # Non-specified but useful for predictability
    NYLAS_CREATE_FAILED = "NYLAS_CREATE_FAILED"
    NYLAS_STATUS_FAILED = "NYLAS_STATUS_FAILED"


@dataclass(frozen=True)
class MeetingRunResult:
    """Structured outcome for one calendar event occurrence.

    This is intentionally small and JSON-serializable so we can persist it to disk
    for unsupervised runs.
    """

    ok: bool
    failure_code: FailureCode | None
    message: str
    event_id: str
    event_start_utc: str
    event_end_utc: str
    meeting_link: str

    attempted_notetaker_ids: list[str]
    final_notetaker_id: str | None

    started_at_utc: str
    ended_at_utc: str

    raw: dict[str, Any] | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "failure_code": self.failure_code.value if self.failure_code else None,
            "message": self.message,
            "event_id": self.event_id,
            "event_start_utc": self.event_start_utc,
            "event_end_utc": self.event_end_utc,
            "meeting_link": self.meeting_link,
            "attempted_notetaker_ids": list(self.attempted_notetaker_ids),
            "final_notetaker_id": self.final_notetaker_id,
            "started_at_utc": self.started_at_utc,
            "ended_at_utc": self.ended_at_utc,
            "raw": self.raw,
        }
