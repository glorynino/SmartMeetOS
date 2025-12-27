from __future__ import annotations

import argparse
import datetime as dt
import json
from typing import Any

from smartmeetos.calendar.google_calendar import utc_now
from smartmeetos.notetaker.supervisor import SupervisorConfig, supervise_meeting


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Join/supervise ONE meeting link via Nylas Notetaker, then wait for and print the transcript.\n\n"
            "Good for quick manual testing (talk in the meeting, then end it)."
        )
    )
    p.add_argument("--meeting-link", required=True, help="Meeting URL (Google Meet / Zoom / Teams)")
    p.add_argument("--grant-id", required=True, help="Nylas grant id")
    p.add_argument("--event-id", default=None, help="Optional synthetic event id (default: manual-<timestamp>)")
    p.add_argument("--summary", default="Manual single-meeting test", help="Synthetic event summary")
    p.add_argument(
        "--duration-minutes",
        type=int,
        default=30,
        help="Synthetic event duration used for supervision bounds (default: 30)",
    )
    p.add_argument("--name", default="Nylas Notetaker", help="Notetaker display name")

    p.add_argument("--nylas-api-key", default=None, help="Nylas API key (or set NYLAS_API_KEY env var)")
    p.add_argument(
        "--nylas-api-base",
        default=None,
        help="Nylas API base URL (default: https://api.us.nylas.com or NYLAS_API_BASE)",
    )

    p.add_argument(
        "--post-end-wait-seconds",
        type=int,
        default=20 * 60,
        help="How long to poll for transcript after meeting ends (default: 1200)",
    )
    p.add_argument(
        "--post-end-poll-seconds",
        type=int,
        default=20,
        help="Polling interval while waiting for transcript (default: 20)",
    )
    p.add_argument(
        "--max-entry-denials",
        type=int,
        default=3,
        help="Stop after this many host denials (default: 3)",
    )

    p.add_argument(
        "--no-transcription",
        action="store_true",
        help="Disable transcription (default: enabled)",
    )
    p.add_argument(
        "--no-audio-recording",
        action="store_true",
        help="Disable audio recording (default: enabled)",
    )

    return p


def _format_transcript(obj: Any) -> str:
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

    started = utc_now()
    event_start = started
    event_end = started + dt.timedelta(minutes=max(1, args.duration_minutes))

    event_id = args.event_id or f"manual-{int(started.timestamp())}"

    meeting_settings = {
        "transcription": not args.no_transcription,
        "audio_recording": not args.no_audio_recording,
    }

    config = SupervisorConfig(
        max_entry_denials=max(1, args.max_entry_denials),
        post_end_transcript_wait_seconds=max(0, args.post_end_wait_seconds),
        post_end_transcript_poll_seconds=max(1, args.post_end_poll_seconds),
    )

    result = supervise_meeting(
        event_id=event_id,
        event_summary=args.summary,
        meeting_link=args.meeting_link,
        event_start=event_start,
        event_end=event_end,
        grant_id=args.grant_id,
        api_key=args.nylas_api_key,
        api_base=args.nylas_api_base,
        notetaker_name=args.name,
        config=config,
        meeting_settings=meeting_settings,
        dry_run=False,
    )

    print("\n=== RESULT ===")
    print(json.dumps(result.to_json(), indent=2))

    # If transcript was saved to disk by the supervisor, it will be under .secrets/transcripts.
    # For convenience, try to print it from `raw.transcript_path` if present.
    raw = result.raw if isinstance(result.raw, dict) else None
    transcript_path = raw.get("transcript_path") if isinstance(raw, dict) else None
    if isinstance(transcript_path, str) and transcript_path:
        try:
            p = dt  # keep linters quiet about unused dt in minimal environments
            _ = p
            text = open(transcript_path, "r", encoding="utf-8").read()
            try:
                obj = json.loads(text)
                print("\n=== TRANSCRIPT (formatted) ===")
                print(_format_transcript(obj))
            except Exception:
                print("\n=== TRANSCRIPT (raw) ===")
                print(text)
        except Exception as e:
            print(f"\nCould not read transcript file {transcript_path}: {e}")

    return 0 if result.ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
