from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _now_ms() -> int:
    return int(time.time() * 1000)


def _safe_mkdir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_json(path: Path, payload: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _get_signature(headers: dict[str, str]) -> str | None:
    # Nylas says: `x-nylas-signature` or `X-Nylas-Signature` depending on framework.
    for k, v in headers.items():
        if k.lower() == "x-nylas-signature":
            return v
    return None


def _verify_signature(*, body: bytes, signature_hex: str, webhook_secret: str) -> bool:
    computed = hmac.new(webhook_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(computed, signature_hex)


def _extract_media_url(val: Any) -> str | None:
    # Webhook schema shows strings; API /media returns dict objects.
    if isinstance(val, str):
        return val
    if isinstance(val, dict):
        url = val.get("url")
        return url if isinstance(url, str) else None
    return None


class _Handler(BaseHTTPRequestHandler):
    server: "_WebhookHTTPServer"  # type: ignore[assignment]

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003 (BaseHTTPRequestHandler API)
        # Keep logs short and readable.
        msg = format % args
        print(f"[{self.log_date_time_string()}] {self.address_string()} {msg}")

    def _send_text(self, status: int, body: str) -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, status: int, payload: Any) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802 (BaseHTTPRequestHandler API)
        # Nylas verification: GET <url>?challenge=... and respond with body exactly equal to challenge.
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        challenge_vals = qs.get("challenge")
        if challenge_vals and isinstance(challenge_vals[0], str):
            self._send_text(200, challenge_vals[0])
            return

        self._send_text(200, "ok")

    def do_POST(self) -> None:  # noqa: N802 (BaseHTTPRequestHandler API)
        length = self.headers.get("Content-Length")
        try:
            body_len = int(length) if length is not None else 0
        except Exception:
            body_len = 0

        body = self.rfile.read(body_len) if body_len > 0 else b""

        headers = {k: v for (k, v) in self.headers.items()}
        signature = _get_signature(headers)

        if self.server.webhook_secret:
            if not signature:
                self._send_json(400, {"error": "missing x-nylas-signature"})
                return
            if not _verify_signature(body=body, signature_hex=signature, webhook_secret=self.server.webhook_secret):
                self._send_json(401, {"error": "invalid signature"})
                return

        try:
            payload = json.loads(body.decode("utf-8")) if body else {}
        except Exception:
            self._send_json(400, {"error": "invalid json"})
            return

        # Always acknowledge quickly.
        self._send_json(200, {"ok": True})

        try:
            self.server.process_notification(payload)
        except Exception as exc:
            # Don't fail the webhook delivery because of our local processing.
            print(f"[webhook] processing error: {exc!r}")


class _WebhookHTTPServer(HTTPServer):
    def __init__(
        self,
        server_address: tuple[str, int],
        RequestHandlerClass: type[BaseHTTPRequestHandler],
        *,
        webhook_secret: str | None,
        out_dir: Path,
        download_media: bool,
    ) -> None:
        super().__init__(server_address, RequestHandlerClass)
        self.webhook_secret = webhook_secret
        self.out_dir = out_dir
        self.download_media = download_media
        self._dedupe_path = out_dir / "dedupe.json"
        self._dedupe = _load_json(self._dedupe_path).get("seen", {})
        if not isinstance(self._dedupe, dict):
            self._dedupe = {}

    def _mark_seen(self, webhook_id: str) -> bool:
        if webhook_id in self._dedupe:
            return False
        self._dedupe[webhook_id] = _now_ms()
        # Keep dedupe file bounded.
        if len(self._dedupe) > 5000:
            # Drop oldest.
            items = sorted(self._dedupe.items(), key=lambda kv: kv[1])
            self._dedupe = dict(items[-4000:])
        _save_json(self._dedupe_path, {"seen": self._dedupe})
        return True

    def process_notification(self, notification: dict[str, Any]) -> None:
        webhook_id = notification.get("id")
        if not isinstance(webhook_id, str) or not webhook_id:
            webhook_id = f"no-id-{_now_ms()}"

        if not self._mark_seen(webhook_id):
            return

        notif_type = notification.get("type")
        ts = notification.get("time")
        filename = f"{int(ts) if isinstance(ts, (int, float)) else _now_ms()}__{webhook_id}.json"

        received_dir = self.out_dir / "received"
        _safe_mkdir(received_dir)
        (received_dir / filename).write_text(
            json.dumps(notification, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        if notif_type != "notetaker.media":
            return

        data = notification.get("data")
        if not isinstance(data, dict):
            return
        obj = data.get("object")
        if not isinstance(obj, dict):
            return

        # Docs: object.state is one of processing/available/error/deleted
        state = obj.get("state")
        notetaker_id = obj.get("id")
        media = obj.get("media")

        if not isinstance(notetaker_id, str) or not notetaker_id:
            return

        media_dir = self.out_dir / "media" / notetaker_id
        _safe_mkdir(media_dir)
        (media_dir / "latest_notetaker_media.json").write_text(
            json.dumps(obj, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        if state != "available":
            return
        if not self.download_media:
            return

        if not isinstance(media, dict):
            return

        transcript_url = _extract_media_url(media.get("transcript"))
        if not transcript_url:
            return

        # Download transcript immediately.
        import requests  # local import to keep startup minimal

        resp = requests.get(transcript_url, timeout=60.0)
        resp.raise_for_status()

        # Save as bytes (it might be JSON, but keep raw).
        out_path = media_dir / "transcript.json"
        out_path.write_bytes(resp.content)

        # Also save headers/metadata.
        meta = {
            "downloaded_at_ms": _now_ms(),
            "transcript_url": transcript_url,
            "content_type": resp.headers.get("Content-Type"),
            "content_length": resp.headers.get("Content-Length"),
        }
        (media_dir / "transcript_meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        print(f"[webhook] downloaded transcript for notetaker_id={notetaker_id} -> {out_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Local receiver for Nylas webhooks (incl. notetaker.media).")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--out-dir",
        default=os.path.join(".secrets", "webhooks"),
        help="Where to store webhook payloads and downloaded media.",
    )
    parser.add_argument(
        "--webhook-secret",
        default=os.environ.get("NYLAS_WEBHOOK_SECRET"),
        help="Webhook secret from Nylas (env: NYLAS_WEBHOOK_SECRET). If set, signatures are verified.",
    )
    parser.add_argument(
        "--no-download-media",
        action="store_true",
        help="Only store payloads; do not download transcript/media URLs.",
    )

    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    _safe_mkdir(out_dir)

    server = _WebhookHTTPServer(
        (args.host, args.port),
        _Handler,
        webhook_secret=args.webhook_secret,
        out_dir=out_dir,
        download_media=(not args.no_download_media),
    )

    print(f"Listening on http://{args.host}:{args.port}")
    print("- GET with ?challenge=... returns challenge for Nylas verification")
    if args.webhook_secret:
        print("- Signature verification: ENABLED")
    else:
        print("- Signature verification: DISABLED (set NYLAS_WEBHOOK_SECRET to enable)")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
