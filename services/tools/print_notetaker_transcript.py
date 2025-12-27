from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from smartmeetos.notetaker.nylas_media import download_media_url, get_notetaker_media_links


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Fetch and print a Nylas Notetaker transcript.")
    p.add_argument("--grant-id", required=True, help="Nylas grant id")
    p.add_argument("--notetaker-id", required=True, help="Nylas notetaker id")
    p.add_argument("--nylas-api-key", default=None, help="Nylas API key (or set NYLAS_API_KEY env var)")
    p.add_argument(
        "--nylas-api-base",
        default=None,
        help="Nylas API base URL (default: https://api.us.nylas.com or NYLAS_API_BASE)",
    )
    p.add_argument(
        "--wait-seconds",
        type=int,
        default=0,
        help="If >0, poll until transcript is available (default: 0)",
    )
    p.add_argument(
        "--poll-seconds",
        type=int,
        default=10,
        help="Polling interval when waiting (default: 10)",
    )
    p.add_argument(
        "--max-chars",
        type=int,
        default=0,
        help="If >0, truncate output to this many characters (default: 0 = no limit)",
    )
    return p


def _format_transcript(obj: Any) -> str:
    # Expected formats:
    # 1) {"object":"transcript","type":"speaker_labelled","transcript":[{"speaker","start","end","text"}, ...]}
    # 2) {"object":"transcript","type":"raw","transcript":"..."}
    if not isinstance(obj, dict):
        return json.dumps(obj, ensure_ascii=False, indent=2)

    t = obj.get("type")
    body = obj.get("transcript")

    if t == "raw" and isinstance(body, str):
        return body

    if t == "speaker_labelled" and isinstance(body, list):
        lines: list[str] = []
        for seg in body:
            if not isinstance(seg, dict):
                continue
            speaker = seg.get("speaker")
            text = seg.get("text")
            if not isinstance(text, str) or not text.strip():
                continue
            if isinstance(speaker, str) and speaker.strip():
                lines.append(f"{speaker.strip()}: {text.strip()}")
            else:
                lines.append(text.strip())
        return "\n".join(lines)

    return json.dumps(obj, ensure_ascii=False, indent=2)


def main() -> int:
    args = build_parser().parse_args()

    deadline = time.time() + args.wait_seconds if args.wait_seconds and args.wait_seconds > 0 else None

    while True:
        links = get_notetaker_media_links(
            grant_id=args.grant_id,
            notetaker_id=args.notetaker_id,
            api_key=args.nylas_api_key,
            api_base=args.nylas_api_base,
        )

        transcript_meta = links.transcript
        transcript_url = transcript_meta.get("url") if isinstance(transcript_meta, dict) else None

        if isinstance(transcript_url, str) and transcript_url.startswith("http"):
            raw = download_media_url(url=transcript_url)
            try:
                transcript_obj = json.loads(raw.decode("utf-8"))
            except Exception:
                # Fallback: treat it as plain text
                transcript_obj = raw.decode("utf-8", errors="replace")

            text = _format_transcript(transcript_obj)
            if args.max_chars and args.max_chars > 0:
                text = text[: args.max_chars]
            print(text)
            return 0

        if deadline is None:
            print("Transcript not available yet. Re-run with --wait-seconds to poll.")
            return 2

        if time.time() >= deadline:
            print("Timed out waiting for transcript.")
            return 3

        time.sleep(max(1, args.poll_seconds))


if __name__ == "__main__":
    raise SystemExit(main())
