from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Iterable

from smartmeetos.calendar.google_calendar import utc_now
from smartmeetos.notetaker.supervisor import save_transcript_if_available


def _repo_root() -> Path:
    return Path(__file__).resolve().parent


def _default_results_path() -> Path:
    return _repo_root() / ".secrets" / "meeting_results.json"


def _default_history_dir() -> Path:
    return _repo_root() / ".secrets" / "history"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Continuously harvest transcripts for previously created Notetakers. "
            "Reads ./.secrets/meeting_results.json and downloads transcripts as soon as Nylas publishes them."
        )
    )
    p.add_argument("--grant-id", required=True, help="Nylas grant id")
    p.add_argument("--nylas-api-key", default=None, help="Nylas API key (or set NYLAS_API_KEY env var)")
    p.add_argument(
        "--nylas-api-base",
        default=None,
        help="Nylas API base URL (default: https://api.us.nylas.com or NYLAS_API_BASE)",
    )
    p.add_argument(
        "--results-path",
        default=None,
        help="Path to meeting_results.json (default: ./.secrets/meeting_results.json)",
    )
    p.add_argument(
        "--poll-seconds",
        type=int,
        default=30,
        help="Polling interval for checking transcript readiness (default: 30)",
    )
    p.add_argument(
        "--no-scan-history",
        action="store_true",
        help="Disable scanning ./.secrets/history/*.jsonl for notetaker IDs (default: enabled)",
    )
    p.add_argument(
        "--history-dir",
        default=None,
        help="History directory containing supervisor JSONL logs (default: ./.secrets/history)",
    )
    p.add_argument(
        "--once",
        action="store_true",
        help="Run one harvest pass and exit",
    )
    p.add_argument(
        "--event-id",
        default=None,
        help="If set, only harvest transcripts for this calendar event id",
    )
    return p


def _load_results(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _iter_notetaker_ids(result: dict[str, Any]) -> Iterable[str]:
    ids: list[str] = []
    attempted = result.get("attempted_notetaker_ids")
    if isinstance(attempted, list):
        for nid in attempted:
            if isinstance(nid, str) and nid and nid not in ids:
                ids.append(nid)
    final_id = result.get("final_notetaker_id")
    if isinstance(final_id, str) and final_id and final_id not in ids:
        ids.append(final_id)
    return ids


def _parse_history_context(history_path: Path) -> tuple[str, str] | None:
    """Return (event_id, event_start_utc_iso) if found in supervisor_start log line."""
    try:
        with history_path.open("r", encoding="utf-8") as f:
            for _ in range(50):
                line = f.readline()
                if not line:
                    break
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if not isinstance(obj, dict):
                    continue
                if obj.get("type") != "supervisor_start":
                    continue
                event_id = obj.get("event_id")
                event_start = obj.get("event_start_utc")
                if isinstance(event_id, str) and isinstance(event_start, str):
                    return event_id, event_start
    except Exception:
        return None
    return None


def _iter_history_notetakers(history_path: Path) -> Iterable[str]:
    """Yield notetaker ids that appear in a supervisor history jsonl file."""
    try:
        with history_path.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if not isinstance(obj, dict):
                    continue
                nid = obj.get("notetaker_id")
                if isinstance(nid, str) and nid:
                    yield nid
                # Some log entries may include a list of ids.
                nids = obj.get("notetaker_ids")
                if isinstance(nids, list):
                    for x in nids:
                        if isinstance(x, str) and x:
                            yield x
    except Exception:
        return


def _iter_from_history_dir(history_dir: Path) -> Iterable[tuple[str, str, str]]:
    """Yield (event_id, event_start_utc_iso, notetaker_id) from history logs."""
    if not history_dir.exists():
        return
    for p in sorted(history_dir.glob("*.jsonl")):
        ctx = _parse_history_context(p)
        if not ctx:
            continue
        event_id, event_start = ctx
        seen: set[str] = set()
        for nid in _iter_history_notetakers(p):
            if nid in seen:
                continue
            seen.add(nid)
            yield event_id, event_start, nid


def _transcript_path(*, event_id: str, event_start_utc_iso: str, notetaker_id: str) -> Path:
    # Keep consistent with supervisor naming.
    safe_start = event_start_utc_iso.replace(":", "-")
    return _repo_root() / ".secrets" / "transcripts" / f"{event_id}__{safe_start}__{notetaker_id}.transcript.json"


def harvest_once(
    *,
    grant_id: str,
    api_key: str | None,
    api_base: str | None,
    results_path: Path,
    filter_event_id: str | None,
    scan_history: bool,
    history_dir: Path,
) -> int:
    candidates: list[tuple[str, str, str]] = []

    results = _load_results(results_path)
    if results:
        for _, result in results.items():
            if not isinstance(result, dict):
                continue

            event_id = result.get("event_id")
            event_start = result.get("event_start_utc")

            if not (isinstance(event_id, str) and isinstance(event_start, str)):
                continue

            if filter_event_id and event_id != filter_event_id:
                continue

            for notetaker_id in _iter_notetaker_ids(result):
                candidates.append((event_id, event_start, notetaker_id))

    if scan_history:
        for event_id, event_start, notetaker_id in _iter_from_history_dir(history_dir):
            if filter_event_id and event_id != filter_event_id:
                continue
            candidates.append((event_id, event_start, notetaker_id))

    if not candidates:
        # Not an error: there might simply be nothing to harvest yet.
        print(f"No transcript candidates found. results_path={results_path} history_dir={history_dir}")
        return 0

    saved_count = 0
    checked_count = 0

    # De-dupe across sources.
    seen_keys: set[str] = set()
    for event_id, event_start, notetaker_id in candidates:
        key = f"{event_id}|{event_start}|{notetaker_id}"
        if key in seen_keys:
            continue
        seen_keys.add(key)

        checked_count += 1

        # If already downloaded, skip.
        if _transcript_path(event_id=event_id, event_start_utc_iso=event_start, notetaker_id=notetaker_id).exists():
            continue

        saved = save_transcript_if_available(
            grant_id=grant_id,
            notetaker_id=notetaker_id,
            event_id=event_id,
            event_start_utc_iso=event_start,
            api_key=api_key,
            api_base=api_base,
        )
        if saved is not None:
            saved_count += 1
            print(f"[{utc_now().isoformat()}] saved transcript: event_id={event_id} notetaker_id={notetaker_id}")

    print(f"Harvest pass done: checked={checked_count} saved={saved_count}")
    return 0


def main() -> int:
    args = build_parser().parse_args()

    results_path = Path(args.results_path) if args.results_path else _default_results_path()
    history_dir = Path(args.history_dir) if args.history_dir else _default_history_dir()
    scan_history = not args.no_scan_history

    if args.once:
        return harvest_once(
            grant_id=args.grant_id,
            api_key=args.nylas_api_key,
            api_base=args.nylas_api_base,
            results_path=results_path,
            filter_event_id=args.event_id,
            scan_history=scan_history,
            history_dir=history_dir,
        )

    print(f"Transcript harvester running. results_path={results_path}")
    print("Stop with Ctrl+C.")

    try:
        while True:
            harvest_once(
                grant_id=args.grant_id,
                api_key=args.nylas_api_key,
                api_base=args.nylas_api_base,
                results_path=results_path,
                filter_event_id=args.event_id,
                scan_history=scan_history,
                history_dir=history_dir,
            )
            time.sleep(max(1, args.poll_seconds))
    except KeyboardInterrupt:
        print("\nStopped (KeyboardInterrupt).")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
