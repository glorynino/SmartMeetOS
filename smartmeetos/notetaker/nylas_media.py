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
class NotetakerMediaLinks:
    # Each entry is a dict like:
    # { created_at, expires_at, name, size, ttl, type, url }
    transcript: dict[str, Any] | None
    recording: dict[str, Any] | None
    summary: dict[str, Any] | None
    action_items: dict[str, Any] | None
    thumbnail: dict[str, Any] | None
    raw: dict[str, Any]


def get_notetaker_media_links(
    *,
    grant_id: str,
    notetaker_id: str,
    api_key: str | None = None,
    api_base: str | None = None,
    timeout_seconds: float = 30.0,
) -> NotetakerMediaLinks:
    resolved_api_key = api_key or _api_key_from_env()
    if not resolved_api_key:
        raise ValueError("Missing Nylas API key. Pass --nylas-api-key or set NYLAS_API_KEY.")

    base = (api_base or _default_api_base()).rstrip("/")
    url = f"{base}/v3/grants/{grant_id}/notetakers/{notetaker_id}/media"

    headers = {
        "Accept": "application/json, application/gzip",
        "Authorization": f"Bearer {resolved_api_key}",
    }

    resp = requests.get(url, headers=headers, timeout=timeout_seconds)
    try:
        data = resp.json()
    except Exception:
        data = {"status_code": resp.status_code, "text": resp.text}

    if resp.status_code >= 400:
        raise RuntimeError(f"Nylas Notetaker media fetch failed ({resp.status_code}): {data}")

    payload = data.get("data") if isinstance(data, dict) else None
    if not isinstance(payload, dict):
        payload = {}

    def pick(key: str) -> dict[str, Any] | None:
        val = payload.get(key)
        return val if isinstance(val, dict) else None

    return NotetakerMediaLinks(
        transcript=pick("transcript"),
        recording=pick("recording"),
        summary=pick("summary"),
        action_items=pick("action_items"),
        thumbnail=pick("thumbnail"),
        raw=data if isinstance(data, dict) else {"data": data},
    )


def download_media_url(
    *,
    url: str,
    timeout_seconds: float = 60.0,
) -> bytes:
    resp = requests.get(url, timeout=timeout_seconds)
    resp.raise_for_status()
    return resp.content
