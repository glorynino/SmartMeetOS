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
    grant_url = f"{base}/v3/grants/{grant_id}/notetakers/{notetaker_id}/media"
    standalone_url = f"{base}/v3/notetakers/{notetaker_id}/media"

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
    # media route may return 404 not_found / 'notetaker not found'. In that case retry
    # once using the standalone media URL.
    if resp.status_code == 404:
        err = data.get("error") if isinstance(data, dict) else None
        msg = err.get("message") if isinstance(err, dict) else None
        if isinstance(msg, str) and "notetaker not found" in msg.lower():
            resp2, data2 = do_get(standalone_url)
            if resp2.status_code < 400:
                resp, data = resp2, data2

    # Nylas can return 410 when no media will be produced or media has been purged.
    # Treat it as a non-fatal "no media available" condition so callers can continue.
    if resp.status_code == 410:
        return NotetakerMediaLinks(
            transcript=None,
            recording=None,
            summary=None,
            action_items=None,
            thumbnail=None,
            raw=data if isinstance(data, dict) else {"data": data},
        )

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
