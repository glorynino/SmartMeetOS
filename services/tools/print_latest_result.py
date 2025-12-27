from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    # This file lives at services/tools/*.py
    return Path(__file__).resolve().parents[2]


def _results_path() -> Path:
    return _repo_root() / ".secrets" / "meeting_results.json"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Print the most recent meeting supervision result.")
    p.add_argument(
        "--path",
        default=None,
        help="Optional path to meeting_results.json (default: ./.secrets/meeting_results.json)",
    )
    p.add_argument(
        "--event-id",
        default=None,
        help="If set, only consider results for this event_id",
    )
    p.add_argument(
        "--raw",
        action="store_true",
        help="Print raw JSON for the selected result",
    )
    return p


def _as_str(v: Any) -> str:
    return v if isinstance(v, str) else ""


def _sort_key(item: dict[str, Any]) -> str:
    # Prefer ended_at_utc; fall back to started_at_utc; final fallback empty string.
    ended = _as_str(item.get("ended_at_utc"))
    if ended:
        return ended
    started = _as_str(item.get("started_at_utc"))
    return started


def main() -> int:
    args = build_parser().parse_args()

    path = Path(args.path) if args.path else _results_path()
    if not path.exists():
        print(f"No results file found at: {path}")
        return 2

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"Failed to read results JSON: {e}")
        return 3

    if not isinstance(data, dict) or not data:
        print("Results file is empty.")
        return 0

    results: list[dict[str, Any]] = []
    for _, val in data.items():
        if not isinstance(val, dict):
            continue
        if args.event_id and _as_str(val.get("event_id")) != args.event_id:
            continue
        results.append(val)

    if not results:
        if args.event_id:
            print(f"No results found for event_id={args.event_id}")
        else:
            print("No results found.")
        return 0

    results.sort(key=_sort_key)
    latest = results[-1]

    if args.raw:
        print(json.dumps(latest, indent=2, ensure_ascii=False))
        return 0

    ok = latest.get("ok")
    failure_code = latest.get("failure_code")
    message = latest.get("message")
    event_id = latest.get("event_id")
    start = latest.get("event_start_utc")
    end = latest.get("event_end_utc")
    final_notetaker_id = latest.get("final_notetaker_id")

    print(f"ok:              {ok}")
    print(f"failure_code:    {failure_code}")
    print(f"message:         {message}")
    print(f"event_id:        {event_id}")
    print(f"event_start_utc: {start}")
    print(f"event_end_utc:   {end}")
    print(f"notetaker_id:    {final_notetaker_id}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
