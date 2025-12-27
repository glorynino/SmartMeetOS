from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass
from typing import Any

import requests


@dataclass(frozen=True)
class NotetakerCreateResult:
    id: str | None
    raw: dict[str, Any]


def _request_with_retry(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    json_body: dict[str, Any] | None = None,
    timeout_seconds: float,
    max_attempts: int = 4,
) -> requests.Response:
    # Conservative retries for transient issues.
    # - Retries: timeouts, connection errors, 429, 5xx.
    # - No retries for other 4xx.
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            resp = requests.request(
                method,
                url,
                headers=headers,
                json=json_body,
                timeout=timeout_seconds,
            )
        except (requests.Timeout, requests.ConnectionError) as e:
            last_exc = e
            resp = None

        if resp is not None:
            if resp.status_code < 400:
                return resp

            # Retry on rate limit and server errors.
            if resp.status_code == 429 or 500 <= resp.status_code <= 599:
                retry_after = resp.headers.get("Retry-After")
                delay: float
                if retry_after and retry_after.isdigit():
                    delay = float(retry_after)
                else:
                    delay = min(30.0, 1.0 * (2 ** (attempt - 1)))
                    delay += random.uniform(0.0, 0.25)
            else:
                # Non-retriable (likely config/auth/payload problem).
                return resp
        else:
            delay = min(30.0, 1.0 * (2 ** (attempt - 1)))
            delay += random.uniform(0.0, 0.25)

        if attempt < max_attempts:
            time.sleep(delay)

    if last_exc:
        raise last_exc
    raise RuntimeError("Request failed after retries")


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
    grant_url = f"{base}/v3/grants/{grant_id}/notetakers" if grant_id else None
    standalone_url = f"{base}/v3/notetakers"
    url = grant_url or standalone_url

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

    def do_post(post_url: str) -> tuple[requests.Response, dict[str, Any]]:
        r = _request_with_retry(
            "POST",
            post_url,
            headers=headers,
            json_body=payload,
            timeout_seconds=timeout_seconds,
        )
        # Return useful debugging info if something goes wrong.
        try:
            d = r.json()
        except Exception:
            d = {"status_code": r.status_code, "text": r.text}
        return r, d

    resp, data = do_post(url)

    # Reliability fallback:
    # Some Nylas accounts/regions may not expose the grant-scoped Notetaker route.
    # If the route itself is missing (404 Cannot POST ...), retry once using the
    # standalone endpoint.
    if grant_url and resp.status_code == 404:
        text = data.get("text") if isinstance(data, dict) else None
        if isinstance(text, str) and "Cannot POST" in text and "/v3/grants/" in text:
            resp2, data2 = do_post(standalone_url)
            if resp2.status_code < 400:
                resp, data = resp2, data2
            else:
                raise RuntimeError(
                    "Nylas Notetaker create failed on grant endpoint (404 route missing) and "
                    f"standalone endpoint also failed ({resp2.status_code}): {data2}"
                )

    if resp.status_code >= 400:
        raise RuntimeError(f"Nylas Notetaker create failed ({resp.status_code}): {data}")

    # Nylas responses generally wrap the object under `data`.
    obj = data.get("data") if isinstance(data, dict) else None
    notetaker_id = None
    if isinstance(obj, dict) and isinstance(obj.get("id"), str):
        notetaker_id = obj["id"]

    return NotetakerCreateResult(id=notetaker_id, raw=data)
