from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from smartmeetos.calendar.google_calendar import GoogleCalendar, default_paths, get_credentials


@dataclass(frozen=True)
class MeetEvent:
    """Small service-layer DTO for Meet events."""

    event_id: str
    summary: str
    start_utc_iso: str
    end_utc_iso: str
    meet_url: str


def build_google_calendar(*, calendar_id: str = "primary") -> GoogleCalendar:
    """Create a GoogleCalendar client using repo-default OAuth paths."""

    paths = default_paths()
    creds = get_credentials(paths)
    return GoogleCalendar(creds=creds, calendar_id=calendar_id)


def list_calendars() -> list[dict]:
    """Return available calendars as dicts (id/summary/etc)."""

    paths = default_paths()
    creds = get_credentials(paths)
    return GoogleCalendar(creds=creds, calendar_id="primary").list_calendars()


def list_meet_events(
    *,
    calendar_id: str = "primary",
    time_min_utc: str,
    time_max_utc: str,
) -> list[MeetEvent]:
    """List Google Calendar events in a window that contain a Meet link.

    Args:
        time_min_utc: RFC3339/ISO string.
        time_max_utc: RFC3339/ISO string.
    """

    cal = build_google_calendar(calendar_id=calendar_id)
    events = cal.list_events(time_min_utc=time_min_utc, time_max_utc=time_max_utc)

    out: list[MeetEvent] = []
    for ev in events:
        if not ev.meet_url:
            continue
        out.append(
            MeetEvent(
                event_id=ev.id,
                summary=ev.summary,
                start_utc_iso=ev.start_utc.isoformat(),
                end_utc_iso=ev.end_utc.isoformat(),
                meet_url=ev.meet_url,
            )
        )

    return out
