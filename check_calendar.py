from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from smartmeetos.calendar.google_calendar import (
    GoogleCalendar,
    default_paths,
    get_credentials,
    local_now,
    parse_minutes,
    utc_now,
)
from smartmeetos.notetaker.nylas_notetaker import create_notetaker
from smartmeetos.notetaker.active_lock import acquire_active_lock, release_active_lock
from smartmeetos.notetaker.failure_codes import FailureCode, MeetingRunResult
from smartmeetos.notetaker.supervisor import SupervisorConfig, supervise_meeting


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Check Google Calendar for upcoming Meet events.")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not create Notetakers or run commands; only print what would happen",
    )
    p.add_argument(
        "--list-calendars",
        action="store_true",
        help="List available calendars (id/summary) and exit",
    )
    p.add_argument("--calendar", default="primary", help="Calendar ID (default: primary)")
    p.add_argument(
        "--window-minutes",
        default="120",
        help="Look ahead window in minutes (default: 120)",
    )
    p.add_argument(
        "--trigger-before-minutes",
        default="2",
        help="Print TRIGGER when a meeting starts within this many minutes (default: 2)",
    )
    p.add_argument(
        "--trigger-after-start-minutes",
        default="10",
        help="Keep triggering eligible meetings up to N minutes after start (default: 10)",
    )
    p.add_argument(
        "--on-trigger-cmd",
        default=None,
        help=(
            "Optional shell command to run once per triggered meeting. "
            "Supports placeholders: {meet_url} {event_id} {summary} {start_utc}."
        ),
    )
    p.add_argument(
        "--nylas-notetaker",
        action="store_true",
        help="Create a Nylas Notetaker when a meeting is triggered (requires NYLAS_API_KEY)",
    )
    p.add_argument(
        "--nylas-api-key",
        default=None,
        help="Nylas API key (or set NYLAS_API_KEY env var)",
    )
    p.add_argument(
        "--nylas-api-base",
        default=None,
        help="Nylas API base URL (default: https://api.us.nylas.com or NYLAS_API_BASE)",
    )
    p.add_argument(
        "--nylas-grant-id",
        default=None,
        help="Optional Nylas grant id to create a grant-based Notetaker",
    )
    p.add_argument(
        "--nylas-notetaker-name",
        default="Nylas Notetaker",
        help="Optional Notetaker display name (default: Nylas Notetaker)",
    )
    p.add_argument(
        "--nylas-status-poll-seconds",
        default=None,
        type=int,
        help=(
            "How often to poll Nylas history for meeting_state while supervising (default: 15). "
            "Lower is faster but increases API calls."
        ),
    )
    p.add_argument(
        "--nylas-transcript-poll-seconds",
        default=None,
        type=int,
        help=(
            "How often the automatic transcript harvester polls Nylas media after a run ends (default: 20). "
            "Lower is faster but increases API calls."
        ),
    )
    p.add_argument(
        "--nylas-max-kicks",
        default=None,
        type=int,
        help="Stop rejoining after being kicked/removed this many times (default: 3)",
    )
    p.add_argument(
        "--nylas-max-denials",
        default=None,
        type=int,
        help="Stop rejoining after being denied entry this many times (default: 3)",
    )
    p.add_argument(
        "--poll-seconds",
        default=0,
        type=int,
        help="If set to >0, re-check every N seconds (default: 0 = run once)",
    )
    p.add_argument(
        "--max-results",
        default=25,
        type=int,
        help="Maximum events to fetch (default: 25)",
    )
    p.add_argument(
        "--client-secret",
        default=None,
        help="Path to OAuth client secret JSON. If omitted, uses GOOGLE_CLIENT_SECRET_FILE or ./secrets/client_secret.json",
    )
    p.add_argument(
        "--token-file",
        default=None,
        help="Path to store OAuth token JSON. If omitted, uses ./.secrets/google_token.json",
    )
    return p


def _trigger_state_path() -> Path:
    env = os.environ.get("SMARTMEETOS_STATE_DIR")
    base = Path(env) if env else (Path(__file__).resolve().parent / ".secrets")
    return base / "trigger_state.json"


def _meeting_results_path() -> Path:
    env = os.environ.get("SMARTMEETOS_STATE_DIR")
    base = Path(env) if env else (Path(__file__).resolve().parent / ".secrets")
    return base / "meeting_results.json"


def _load_meeting_results(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _save_meeting_results(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _load_trigger_state(path: Path) -> dict[str, str]:
    # Maps event_id -> start_utc_iso, so we trigger each occurrence once.
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        # Corrupted state file; back it up so we don't crash or spam.
        try:
            backup = path.with_suffix(path.suffix + ".corrupt")
            if path.exists():
                path.replace(backup)
        except Exception:
            pass
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in data.items():
        if isinstance(k, str) and isinstance(v, str):
            out[k] = v
    return out


def _save_trigger_state(path: Path, state: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _maybe_run_trigger_cmd(cmd_template: str, *, event_id: str, summary: str, meet_url: str, start_utc: str) -> bool:
    cmd = (
        cmd_template.replace("{event_id}", event_id)
        .replace("{summary}", summary)
        .replace("{meet_url}", meet_url)
        .replace("{start_utc}", start_utc)
    )
    print(f"  RUN: {cmd}")
    result = subprocess.run(cmd, shell=True, check=False)
    if result.returncode != 0:
        print(f"  RUN: command exited with code {result.returncode}")
        return False
    return True


def run_once(args: argparse.Namespace) -> int:
    window_minutes = parse_minutes(args.window_minutes)
    trigger_before = parse_minutes(args.trigger_before_minutes)
    trigger_after = parse_minutes(args.trigger_after_start_minutes)

    default_client_secret, default_token_file = default_paths()
    client_secret_file = Path(args.client_secret) if args.client_secret else default_client_secret
    token_file = Path(args.token_file) if args.token_file else default_token_file

    if not client_secret_file.exists():
        raise FileNotFoundError(
            f"Client secret not found at: {client_secret_file}. "
            "Place it there or pass --client-secret / set GOOGLE_CLIENT_SECRET_FILE."
        )

    creds = get_credentials(
        client_secret_file=client_secret_file,
        token_file=token_file,
    )

    calendar = GoogleCalendar(creds)

    if args.list_calendars:
        calendars = calendar.list_calendars()
        print("Available calendars:")
        for cal in calendars:
            primary = " (primary)" if cal.get("primary") else ""
            print(f"- {cal.get('summary')}  id={cal.get('id')}{primary}")
        return 0

    now_utc = utc_now()
    # Late-join support:
    # In addition to upcoming events, also fetch events that started recently so we can detect
    # meetings already in progress (start <= now < end). We reuse --window-minutes as the lookback
    # horizon so behavior can be adjusted without adding new CLI flags.
    lookback = dt.timedelta(minutes=window_minutes)
    time_min = now_utc
    time_max = now_utc + dt.timedelta(minutes=window_minutes)

    print(f"Calendar ID: {args.calendar}")
    upcoming_events = calendar.list_upcoming_events(
        calendar_id=args.calendar,
        time_min=time_min,
        time_max=time_max,
        max_results=args.max_results,
    )
    # Fetch recently-started events so ongoing meetings can be detected.
    recent_events = calendar.list_upcoming_events(
        calendar_id=args.calendar,
        time_min=now_utc - lookback,
        time_max=now_utc,
        max_results=args.max_results,
    )

    # Merge and de-duplicate by (event_id, start_utc) so we can safely combine the two queries.
    events: list[Any] = []
    seen_keys: set[str] = set()
    for ev in (recent_events + upcoming_events):
        start_utc = ev.start.astimezone(dt.timezone.utc)
        key = f"{ev.id}|{start_utc.isoformat()}"
        if key in seen_keys:
            continue
        seen_keys.add(key)
        events.append(ev)

    now_local = local_now()
    print(f"Now (local): {now_local.isoformat()}")
    print(f"Now (UTC):   {now_utc.isoformat()}")
    print(f"Looking ahead: {window_minutes} minutes")
    print(f"Found {len(events)} events\n")

    trigger_state_path = _trigger_state_path()
    trigger_state = _load_trigger_state(trigger_state_path)

    results_path = _meeting_results_path()
    meeting_results = _load_meeting_results(results_path)

    # Mandatory policy: only one meeting can be active at a time.
    # If multiple meetings are eligible in the same poll, we pick the earliest and skip the rest.
    eligible_events: list[tuple[dt.datetime, Any]] = []

    for ev in events:
        # Ignore cancelled events (defensive: should already be filtered by API params)
        status = ev.raw.get("status") if isinstance(ev.raw, dict) else None
        is_cancelled = status == "cancelled"

        # Ignore all-day events for triggering.
        start_obj = ev.raw.get("start") if isinstance(ev.raw, dict) else None
        is_all_day = isinstance(start_obj, dict) and isinstance(start_obj.get("date"), str) and not start_obj.get("dateTime")

        start_utc = ev.start.astimezone(dt.timezone.utc)
        end_utc = ev.end.astimezone(dt.timezone.utc)
        delta = start_utc - now_utc
        start_local = ev.start.astimezone(now_local.tzinfo)
        minutes_until = int(delta.total_seconds() // 60)

        is_ended = now_utc >= end_utc
        is_ongoing = (start_utc <= now_utc) and (now_utc < end_utc)

        # Trigger window for generic actions.
        trigger_window_start = start_utc - dt.timedelta(minutes=trigger_before)
        trigger_window_end = start_utc + dt.timedelta(minutes=trigger_after)
        due_now = trigger_window_start <= now_utc <= trigger_window_end

        # Mandatory join timing window for Nylas Notetaker behavior.
        # Join attempts allowed between: T_start − 2 minutes and T_start + 15 minutes
        nylas_window_start = start_utc - dt.timedelta(minutes=2)
        nylas_window_end = start_utc + dt.timedelta(minutes=15)
        due_now_nylas = nylas_window_start <= now_utc <= nylas_window_end

        meet = ev.meet_url or "(no Meet link found)"
        print(f"- {ev.summary}")
        print(f"  start: {start_local.isoformat()} ({minutes_until:+} min)")
        print(f"  meet:  {meet}")

        if ev.meet_url and "meet.google.com" not in ev.meet_url:
            print("  (skipping: non-Google-Meet link)")
            print("")
            continue

        if is_cancelled:
            print("  (skipping: cancelled event)")
            print("")
            continue

        if is_all_day:
            print("  (skipping: all-day event)")
            print("")
            continue

        if is_ended:
            print("  (skipping: already ended)")
            print("")
            continue

        # Late join logic:
        # - If the meeting is ongoing (start <= now < end), allow creating a Notetaker even if
        #   it started before the trigger window.
        # - For future meetings, keep the existing trigger window behavior.
        eligible = False
        if ev.meet_url:
            if is_ongoing:
                eligible = True
            else:
                eligible = (due_now_nylas if args.nylas_notetaker else due_now)

        if eligible:
            eligible_events.append((start_utc, ev))
            print("")
            continue

        print("")

    # Process eligible events after printing, so we can enforce overlap policy.
    eligible_events.sort(key=lambda t: t[0])
    if eligible_events:
        # Keep the first eligible event; skip the rest.
        chosen_start_utc, chosen_ev = eligible_events[0]

        for _, other_ev in eligible_events[1:]:
            other_start_utc = other_ev.start.astimezone(dt.timezone.utc)
            other_key = f"{other_ev.id}|{other_start_utc.isoformat()}"

            print(f"- {other_ev.summary}")
            print("  SKIPPED: OVERLAP_CONFLICT (another meeting is being handled)")

            if not args.dry_run:
                trigger_state[other_ev.id] = other_start_utc.isoformat()
                _save_trigger_state(trigger_state_path, trigger_state)

                meeting_results[other_key] = MeetingRunResult(
                    ok=False,
                    failure_code=FailureCode.SKIPPED_OVERLAP_CONFLICT,
                    message="Skipped due to overlap conflict (single active meeting policy).",
                    event_id=other_ev.id,
                    event_start_utc=other_start_utc.isoformat(),
                    event_end_utc=other_ev.end.astimezone(dt.timezone.utc).isoformat(),
                    meeting_link=other_ev.meet_url or "",
                    attempted_notetaker_ids=[],
                    final_notetaker_id=None,
                    started_at_utc=now_utc.isoformat(),
                    ended_at_utc=now_utc.isoformat(),
                ).to_json()
                _save_meeting_results(results_path, meeting_results)

            print("")

        # Now handle the chosen event if not already triggered.
        chosen_start_iso = chosen_start_utc.isoformat()
        already = trigger_state.get(chosen_ev.id) == chosen_start_iso
        if already:
            print(f"- {chosen_ev.summary}")
            print("  (already triggered)")
            print("")
            return 0

        if not chosen_ev.meet_url:
            return 0

        print(f"- {chosen_ev.summary}")
        print("  TRIGGER: attempting Notetaker join with retries/timeouts")

        # Acquire lock (expires at event_end + 30m), enforcing single active meeting.
        expires_at = (chosen_ev.end.astimezone(dt.timezone.utc) + dt.timedelta(minutes=30)).isoformat()
        lock_ok = True
        if not args.dry_run:
            lock_ok = acquire_active_lock(
                event_id=chosen_ev.id,
                event_start_utc=chosen_start_iso,
                expires_at_utc=expires_at,
            )

        if not lock_ok:
            # Another meeting is still active; mark this one as skipped.
            chosen_key = f"{chosen_ev.id}|{chosen_start_iso}"
            print("  SKIPPED: OVERLAP_CONFLICT (active lock held)")
            if not args.dry_run:
                trigger_state[chosen_ev.id] = chosen_start_iso
                _save_trigger_state(trigger_state_path, trigger_state)

                meeting_results[chosen_key] = MeetingRunResult(
                    ok=False,
                    failure_code=FailureCode.SKIPPED_OVERLAP_CONFLICT,
                    message="Skipped due to overlap conflict (active lock held).",
                    event_id=chosen_ev.id,
                    event_start_utc=chosen_start_iso,
                    event_end_utc=chosen_ev.end.astimezone(dt.timezone.utc).isoformat(),
                    meeting_link=chosen_ev.meet_url,
                    attempted_notetaker_ids=[],
                    final_notetaker_id=None,
                    started_at_utc=now_utc.isoformat(),
                    ended_at_utc=now_utc.isoformat(),
                ).to_json()
                _save_meeting_results(results_path, meeting_results)
            print("")
            return 0

        # Run supervisor (failure-handling logic). This blocks by design so the run is predictable.
        result_obj: MeetingRunResult
        try:
            if args.nylas_notetaker:
                if not args.nylas_grant_id and not args.dry_run:
                    raise ValueError("--nylas-grant-id is required for supervised Notetaker runs")

                result_obj = supervise_meeting(
                    event_id=chosen_ev.id,
                    event_summary=chosen_ev.summary,
                    meeting_link=chosen_ev.meet_url,
                    event_start=chosen_ev.start,
                    event_end=chosen_ev.end,
                    grant_id=args.nylas_grant_id or "",
                    api_key=args.nylas_api_key,
                    api_base=args.nylas_api_base,
                    notetaker_name=args.nylas_notetaker_name,
                    config=SupervisorConfig(
                        status_poll_seconds=(
                            int(args.nylas_status_poll_seconds)
                            if args.nylas_status_poll_seconds is not None
                            else SupervisorConfig.status_poll_seconds
                        ),
                        post_end_transcript_poll_seconds=(
                            int(args.nylas_transcript_poll_seconds)
                            if args.nylas_transcript_poll_seconds is not None
                            else SupervisorConfig.post_end_transcript_poll_seconds
                        ),
                        max_kicks=(
                            int(args.nylas_max_kicks)
                            if args.nylas_max_kicks is not None
                            else SupervisorConfig.max_kicks
                        ),
                        max_entry_denials=(
                            int(args.nylas_max_denials)
                            if args.nylas_max_denials is not None
                            else SupervisorConfig.max_entry_denials
                        ),
                    ),
                    meeting_settings={
                        "transcription": True,
                        "audio_recording": True,
                    },
                    dry_run=bool(args.dry_run),
                )
            else:
                # If Nylas is disabled, treat it as a no-op (generic trigger handling below).
                result_obj = MeetingRunResult(
                    ok=True,
                    failure_code=None,
                    message="No Nylas supervision requested.",
                    event_id=chosen_ev.id,
                    event_start_utc=chosen_start_iso,
                    event_end_utc=chosen_ev.end.astimezone(dt.timezone.utc).isoformat(),
                    meeting_link=chosen_ev.meet_url,
                    attempted_notetaker_ids=[],
                    final_notetaker_id=None,
                    started_at_utc=now_utc.isoformat(),
                    ended_at_utc=now_utc.isoformat(),
                )
        finally:
            if not args.dry_run:
                release_active_lock(event_id=chosen_ev.id, event_start_utc=chosen_start_iso)

        chosen_key = f"{chosen_ev.id}|{chosen_start_iso}"
        print(f"  RESULT: ok={result_obj.ok} failure_code={result_obj.failure_code}")
        if result_obj.failure_code:
            print(f"  MESSAGE: {result_obj.message}")

        # Persist results + mark as triggered so we don't spawn repeated supervisors.
        if not args.dry_run:
            trigger_state[chosen_ev.id] = chosen_start_iso
            _save_trigger_state(trigger_state_path, trigger_state)
            meeting_results[chosen_key] = result_obj.to_json()
            _save_meeting_results(results_path, meeting_results)

        # Optional: still run on-trigger command after a successful supervised run.
        if args.on_trigger_cmd:
            if args.dry_run:
                print("  RUN: (dry-run) would execute on-trigger command")
            else:
                _maybe_run_trigger_cmd(
                    args.on_trigger_cmd,
                    event_id=chosen_ev.id,
                    summary=chosen_ev.summary,
                    meet_url=chosen_ev.meet_url,
                    start_utc=chosen_start_iso,
                )

        print("")

    return 0


def main() -> int:
    args = build_parser().parse_args()

    if args.poll_seconds and args.poll_seconds > 0:
        try:
            while True:
                run_once(args)
                time.sleep(args.poll_seconds)
        except KeyboardInterrupt:
            print("\nStopped (KeyboardInterrupt).")
            return 0

    return run_once(args)


if __name__ == "__main__":
    raise SystemExit(main())
