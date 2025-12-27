from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from smartmeetos.notetaker.transcript_merge import merge_all_meetings_in_dir, merge_transcripts_for_meeting


def _repo_root() -> Path:
    # This file lives at services/tools/*.py
    return Path(__file__).resolve().parents[2]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Merge transcript fragments into one final transcript per meeting.")
    p.add_argument(
        "--dir",
        default=None,
        help="Directory containing <event_id>__<event_start>__<notetaker_id>.transcript.json files (default: ./.secrets/transcripts)",
    )
    p.add_argument("--event-id", default=None, help="If set, merge only this event_id")
    p.add_argument(
        "--event-start",
        default=None,
        help="If set with --event-id, merge only this event_start (ISO or filename token)",
    )
    p.add_argument("--force", action="store_true", help="Overwrite merged outputs if they already exist")
    return p


def main() -> int:
    args = build_parser().parse_args()

    transcripts_dir = Path(args.dir) if args.dir else (_repo_root() / ".secrets" / "transcripts")

    if args.event_id and args.event_start:
        out_json, out_txt = merge_transcripts_for_meeting(
            transcripts_dir=transcripts_dir,
            event_id=args.event_id,
            event_start=args.event_start,
            force=bool(args.force),
        )
        if not out_json or not out_txt:
            # No-op
            return 0
        print(str(out_json))
        print(str(out_txt))
        return 0

    # Merge all meetings found.
    merged = merge_all_meetings_in_dir(transcripts_dir=transcripts_dir, force=bool(args.force))
    for out_json, out_txt in merged:
        print(str(out_json))
        print(str(out_txt))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
