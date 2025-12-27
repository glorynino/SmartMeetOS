from __future__ import annotations

import argparse

from smartmeetos.notetaker.nylas_notetaker import create_notetaker


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Create a fresh Nylas Notetaker for a meeting link (useful if the bot disconnected)."
        )
    )
    p.add_argument("--meeting-link", required=True, help="Meeting URL (Google Meet / Zoom / Teams)")
    p.add_argument("--grant-id", default=None, help="Optional Nylas grant id")
    p.add_argument("--name", default="Nylas Notetaker", help="Notetaker display name")
    p.add_argument("--nylas-api-key", default=None, help="Nylas API key (or set NYLAS_API_KEY env var)")
    p.add_argument(
        "--nylas-api-base",
        default=None,
        help="Nylas API base URL (default: https://api.us.nylas.com or NYLAS_API_BASE)",
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


def main() -> int:
    args = build_parser().parse_args()

    meeting_settings = {
        "transcription": not args.no_transcription,
        "audio_recording": not args.no_audio_recording,
    }

    result = create_notetaker(
        meeting_link=args.meeting_link,
        api_key=args.nylas_api_key,
        api_base=args.nylas_api_base,
        grant_id=args.grant_id,
        name=args.name,
        meeting_settings=meeting_settings,
    )

    print(f"NYLAS: created notetaker id={result.id or '(unknown)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
