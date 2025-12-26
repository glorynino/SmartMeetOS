from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import requests


@dataclass(frozen=True)
class NotetakerCreateResult:
    id: str | None
    raw: dict[str, Any]


def _default_api_base() -> str:
    # Nylas v3 has regional base URLs; US is the default in their examples.
    return os.environ.get("NYLAS_API_BASE", "https://api.us.nylas.com").rstrip("/")


def _api_key_from_env() -> str | None:
    return os.environ.get("NYLAS_API_KEY")


def create_notetaker(
    *,
    meeting_link: str,
    api_key: str | None = None,
    grant_id: str | None = None,
    join_time: int | None = None,
    name: str | None = None,
    meeting_settings: dict[str, Any] | None = None,
    api_base: str | None = None,
    timeout_seconds: float = 30.0,
) -> NotetakerCreateResult:
    """Create a Nylas Notetaker bot.

    Uses either:
      - POST /v3/notetakers (standalone)
      - POST /v3/grants/{grant_id}/notetakers (grant-based)

    Auth:
      Authorization: Bearer <NYLAS_API_KEY>

    Args:
      meeting_link: The Google Meet / Zoom / Teams meeting URL.
      api_key: Nylas API key. If omitted, uses NYLAS_API_KEY.
      grant_id: If provided, uses grant-scoped endpoint.
      join_time: Optional UNIX timestamp (seconds) when Notetaker should join.
      name: Optional bot display name.
      meeting_settings: Optional settings dict.
      api_base: Base URL (e.g., https://api.us.nylas.com). If omitted, uses NYLAS_API_BASE or US default.
    """

    resolved_api_key = api_key or _api_key_from_env()
    if not resolved_api_key:
        raise ValueError("Missing Nylas API key. Pass --nylas-api-key or set NYLAS_API_KEY.")

    base = (api_base or _default_api_base()).rstrip("/")
    if grant_id:
        url = f"{base}/v3/grants/{grant_id}/notetakers"
    else:
        url = f"{base}/v3/notetakers"

    payload: dict[str, Any] = {
        "meeting_link": meeting_link,
    }
    if join_time is not None:
        payload["join_time"] = int(join_time)
    if name:
        payload["name"] = name
    if meeting_settings is not None:
        payload["meeting_settings"] = meeting_settings

    headers = {
        "Accept": "application/json, application/gzip",
        "Authorization": f"Bearer {resolved_api_key}",
        "Content-Type": "application/json",
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=timeout_seconds)
    # Return useful debugging info if something goes wrong.
    try:
        data = resp.json()
    except Exception:
        data = {"status_code": resp.status_code, "text": resp.text}

    if resp.status_code >= 400:
        raise RuntimeError(f"Nylas Notetaker create failed ({resp.status_code}): {data}")

    # Nylas responses generally wrap the object under `data`.
    obj = data.get("data") if isinstance(data, dict) else None
    notetaker_id = None
    if isinstance(obj, dict) and isinstance(obj.get("id"), str):
        notetaker_id = obj["id"]

    return NotetakerCreateResult(id=notetaker_id, raw=data)
