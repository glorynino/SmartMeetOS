from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import requests


def _default_api_base() -> str:
    return os.environ.get("NYLAS_API_BASE", "https://api.us.nylas.com").rstrip("/")


def _api_key_from_env() -> str | None:
    return os.environ.get("NYLAS_API_KEY")


@dataclass(frozen=True)
class NotetakerLatestStatus:
    notetaker_id: str
    event_type: str | None
    state: str | None
    meeting_state: str | None
    created_at: int | None
    raw: dict[str, Any]


def get_notetaker_history(
    *,
    grant_id: str,
    notetaker_id: str,
    api_key: str | None = None,
    api_base: str | None = None,
    timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    resolved_api_key = api_key or _api_key_from_env()
    if not resolved_api_key:
        raise ValueError("Missing Nylas API key. Pass --nylas-api-key or set NYLAS_API_KEY.")

    base = (api_base or _default_api_base()).rstrip("/")
    grant_url = f"{base}/v3/grants/{grant_id}/notetakers/{notetaker_id}/history"
    standalone_url = f"{base}/v3/notetakers/{notetaker_id}/history"

    headers = {
        "Accept": "application/json, application/gzip",
        "Authorization": f"Bearer {resolved_api_key}",
    }

    def do_get(get_url: str) -> tuple[requests.Response, dict[str, Any]]:
        r = requests.get(get_url, headers=headers, timeout=timeout_seconds)
        try:
            d = r.json()
        except Exception:
            d = {"status_code": r.status_code, "text": r.text}
        return r, d

    resp, data = do_get(grant_url)

    # Reliability fallback:
    # If Notetaker was created via standalone endpoint (/v3/notetakers), the grant-scoped
    # history route may return 404 not_found / 'notetaker not found'. In that case retry
    # once using the standalone history URL.
    if resp.status_code == 404:
        err = data.get("error") if isinstance(data, dict) else None
        msg = err.get("message") if isinstance(err, dict) else None
        if isinstance(msg, str) and "notetaker not found" in msg.lower():
            resp2, data2 = do_get(standalone_url)
            if resp2.status_code < 400:
                resp, data = resp2, data2

    if resp.status_code >= 400:
        raise RuntimeError(f"Nylas Notetaker history fetch failed ({resp.status_code}): {data}")

    if not isinstance(data, dict):
        return {"data": data}
    return data


def get_latest_status_from_history(history_payload: dict[str, Any], *, notetaker_id: str) -> NotetakerLatestStatus:
    data = history_payload.get("data") if isinstance(history_payload, dict) else None
    events = None
    if isinstance(data, dict):
        events = data.get("events")

    # Nylas history can include events like `notetaker.media` that are newer than
    # `notetaker.meeting_state` and often do not include a meeting_state.
    # For supervision/debugging we want the most recent event that carries state.
    chosen: dict[str, Any] | None = None
    chosen_obj: dict[str, Any] | None = None

    if isinstance(events, list) and events:
        for ev in events:
            if not isinstance(ev, dict):
                continue
            obj = ev.get("data") if isinstance(ev.get("data"), dict) else None
            meeting_state = obj.get("meeting_state") if isinstance(obj, dict) else None
            state = obj.get("state") if isinstance(obj, dict) else None
            event_type = ev.get("event_type")

            # Prefer explicit meeting_state events.
            if isinstance(meeting_state, str) and meeting_state.strip():
                chosen, chosen_obj = ev, obj
                break

            # Next best: events that carry a state and look like meeting_state events.
            if isinstance(state, str) and state.strip() and isinstance(event_type, str) and "meeting_state" in event_type:
                chosen, chosen_obj = ev, obj
                break

        # Fallback: take the newest event.
        if chosen is None:
            chosen = events[0] if isinstance(events[0], dict) else None
            chosen_obj = chosen.get("data") if isinstance(chosen, dict) and isinstance(chosen.get("data"), dict) else None

    event_type = chosen.get("event_type") if isinstance(chosen, dict) else None
    created_at = chosen.get("created_at") if isinstance(chosen, dict) else None
    state = chosen_obj.get("state") if isinstance(chosen_obj, dict) else None
    meeting_state = chosen_obj.get("meeting_state") if isinstance(chosen_obj, dict) else None

    return NotetakerLatestStatus(
        notetaker_id=notetaker_id,
        event_type=event_type if isinstance(event_type, str) else None,
        state=state if isinstance(state, str) else None,
        meeting_state=meeting_state if isinstance(meeting_state, str) else None,
        created_at=created_at if isinstance(created_at, int) else None,
        raw=history_payload,
    )
