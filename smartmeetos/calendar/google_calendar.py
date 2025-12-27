from __future__ import annotations

import base64
import datetime as dt
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from dateutil import tz
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


DEFAULT_SCOPES: tuple[str, ...] = (
    "https://www.googleapis.com/auth/calendar.readonly",
)


@dataclass(frozen=True)
class CalendarEvent:
    id: str
    summary: str
    start: dt.datetime
    end: dt.datetime
    meet_url: str | None
    raw: dict[str, Any]


def _ensure_datetime(value: str) -> dt.datetime:
    # Google Calendar can return either `dateTime` (RFC3339) or `date` (all-day).
    # We normalize both to an aware datetime.
    if "T" in value:
        # RFC3339 like 2025-12-26T10:00:00+01:00
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=dt.timezone.utc)
        return parsed

    # All-day date like 2025-12-26
    parsed_date = dt.date.fromisoformat(value)
    return dt.datetime.combine(parsed_date, dt.time.min, tzinfo=dt.timezone.utc)


def _extract_meet_url(event: dict[str, Any]) -> str | None:
    # Common field for Meet-created events
    if isinstance(event.get("hangoutLink"), str) and event["hangoutLink"].startswith("http"):
        return event["hangoutLink"]

    # Some events store the Meet link under conferenceData.entryPoints
    conf = event.get("conferenceData")
    if isinstance(conf, dict):
        entry_points = conf.get("entryPoints")
        if isinstance(entry_points, list):
            for ep in entry_points:
                if not isinstance(ep, dict):
                    continue
                uri = ep.get("uri")
                ep_type = ep.get("entryPointType")
                if ep_type in {"video", "more"} and isinstance(uri, str) and "meet.google.com" in uri:
                    return uri

    # Some calendars put it in the location/description
    for key in ("location", "description"):
        value = event.get(key)
        if isinstance(value, str) and "meet.google.com" in value:
            # Very light extraction: return the first token containing meet.google.com
            for token in value.replace("\n", " ").split(" "):
                if "meet.google.com" in token:
                    token = token.strip("<>[](){}\"'.,;")
                    if token.startswith("http"):
                        return token
                    return "https://" + token

    return None


def load_client_config(client_secret_file: Path) -> dict[str, Any]:
    with client_secret_file.open("r", encoding="utf-8") as f:
        config = json.load(f)

    if not isinstance(config, dict) or not any(k in config for k in ("installed", "web")):
        raise ValueError(
            "Client secret JSON must have a top-level 'installed' or 'web' key (Google OAuth client JSON)."
        )

    return config


def get_credentials(
    *,
    client_secret_file: Path,
    token_file: Path,
    scopes: Iterable[str] = DEFAULT_SCOPES,
) -> Credentials:
    creds: Credentials | None = None

    if token_file.exists():
        creds = Credentials.from_authorized_user_file(str(token_file), scopes=list(scopes))

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text(creds.to_json(), encoding="utf-8")
        return creds

    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret_file), scopes=list(scopes))

    # Local server flow opens a browser and receives the auth code on localhost.
    # If your OAuth client type is "Web application", ensure you have an authorized redirect URI
    # like http://localhost:8080/ or create a "Desktop" OAuth client in Google Cloud Console.
    creds = flow.run_local_server(port=8080, prompt="consent")

    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(creds.to_json(), encoding="utf-8")
    return creds


class GoogleCalendar:
    def __init__(self, creds: Credentials):
        self._service = build("calendar", "v3", credentials=creds, cache_discovery=False)

    def list_calendars(self) -> list[dict[str, Any]]:
        result = self._service.calendarList().list().execute()
        items = result.get("items", [])
        if not isinstance(items, list):
            return []

        calendars: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            calendars.append(
                {
                    "id": item.get("id"),
                    "summary": item.get("summary"),
                    "primary": bool(item.get("primary", False)),
                    "accessRole": item.get("accessRole"),
                    "timeZone": item.get("timeZone"),
                }
            )

        return calendars

    def list_upcoming_events(
        self,
        *,
        calendar_id: str = "primary",
        time_min: dt.datetime,
        time_max: dt.datetime,
        max_results: int = 25,
        include_cancelled: bool = False,
    ) -> list[CalendarEvent]:
        if time_min.tzinfo is None or time_max.tzinfo is None:
            raise ValueError("time_min and time_max must be timezone-aware datetimes")

        params: dict[str, Any] = {
            "calendarId": calendar_id,
            "timeMin": time_min.isoformat(),
            "timeMax": time_max.isoformat(),
            "maxResults": max_results,
            "singleEvents": True,
            "orderBy": "startTime",
            "showDeleted": include_cancelled,
            # Some discovery docs/older client versions may not accept this kwarg on events.list.
            # When unsupported, we retry without it.
            "conferenceDataVersion": 1,
        }

        events_resource = self._service.events()
        try:
            result = events_resource.list(**params).execute()
        except TypeError as e:
            if "conferenceDataVersion" not in str(e):
                raise
            params.pop("conferenceDataVersion", None)
            result = events_resource.list(**params).execute()

        items = result.get("items", [])
        if not isinstance(items, list):
            return []

        events: list[CalendarEvent] = []
        for item in items:
            if not isinstance(item, dict):
                continue

            raw_summary = item.get("summary")
            if isinstance(raw_summary, str):
                summary = raw_summary.strip()
            else:
                summary = ""
            if not summary:
                summary = "(no title)"

            start_obj = item.get("start", {})
            end_obj = item.get("end", {})
            if not isinstance(start_obj, dict) or not isinstance(end_obj, dict):
                continue

            start_raw = start_obj.get("dateTime") or start_obj.get("date")
            end_raw = end_obj.get("dateTime") or end_obj.get("date")
            if not isinstance(start_raw, str) or not isinstance(end_raw, str):
                continue

            start_dt = _ensure_datetime(start_raw)
            end_dt = _ensure_datetime(end_raw)

            meet_url = _extract_meet_url(item)
            events.append(
                CalendarEvent(
                    id=str(item.get("id", "")),
                    summary=summary,
                    start=start_dt,
                    end=end_dt,
                    meet_url=meet_url,
                    raw=item,
                )
            )

        return events


def local_now() -> dt.datetime:
    return dt.datetime.now(tz=tz.tzlocal())


def utc_now() -> dt.datetime:
    return dt.datetime.now(tz=dt.timezone.utc)


def parse_minutes(value: str) -> int:
    try:
        minutes = int(value)
    except ValueError as e:
        raise ValueError("minutes must be an integer") from e

    if minutes <= 0:
        raise ValueError("minutes must be > 0")

    return minutes


def default_paths() -> tuple[Path, Path]:
    # Keep secrets out of git: user should place client_secret.json in ./secrets
    repo_root = Path(__file__).resolve().parents[2]

    state_dir_env = os.environ.get("SMARTMEETOS_STATE_DIR")
    state_dir = Path(state_dir_env) if state_dir_env else (repo_root / ".secrets")

    client_secret_env = os.environ.get("GOOGLE_CLIENT_SECRET_FILE")
    client_secret_file = Path(client_secret_env) if client_secret_env else repo_root / "secrets" / "client_secret.json"

    # Optional: provide the client secret JSON contents via env (useful on Render).
    if not client_secret_file.exists():
        raw = os.environ.get("GOOGLE_CLIENT_SECRET_JSON")
        b64 = os.environ.get("GOOGLE_CLIENT_SECRET_JSON_BASE64")
        payload: str | None = None
        if isinstance(raw, str) and raw.strip():
            payload = raw
        elif isinstance(b64, str) and b64.strip():
            try:
                payload = base64.b64decode(b64).decode("utf-8")
            except Exception:
                payload = None
        if isinstance(payload, str) and payload.strip():
            client_secret_file.parent.mkdir(parents=True, exist_ok=True)
            client_secret_file.write_text(payload, encoding="utf-8")

    token_file = state_dir / "google_token.json"

    # Optional: seed the OAuth token JSON via env.
    if not token_file.exists():
        token_seed_file = os.environ.get("GOOGLE_TOKEN_FILE")
        if isinstance(token_seed_file, str) and token_seed_file.strip():
            try:
                payload = Path(token_seed_file).read_text(encoding="utf-8")
                if payload.strip():
                    token_file.parent.mkdir(parents=True, exist_ok=True)
                    token_file.write_text(payload, encoding="utf-8")
            except Exception:
                pass

        raw = os.environ.get("GOOGLE_TOKEN_JSON")
        b64 = os.environ.get("GOOGLE_TOKEN_JSON_BASE64")
        payload: str | None = None
        if isinstance(raw, str) and raw.strip():
            payload = raw
        elif isinstance(b64, str) and b64.strip():
            try:
                payload = base64.b64decode(b64).decode("utf-8")
            except Exception:
                payload = None
        if isinstance(payload, str) and payload.strip():
            token_file.parent.mkdir(parents=True, exist_ok=True)
            token_file.write_text(payload, encoding="utf-8")
    return client_secret_file, token_file
