from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import time
from pathlib import Path

from smartmeetos.calendar.google_calendar import (
    GoogleCalendar,
    default_paths,
    get_credentials,
    local_now,
    parse_minutes,
    utc_now,
)
from smartmeetos.notetaker.nylas_notetaker import create_notetaker


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Check Google Calendar for upcoming Meet events.")
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
    return Path(__file__).resolve().parent / ".secrets" / "trigger_state.json"


def _load_trigger_state(path: Path) -> dict[str, str]:
    # Maps event_id -> start_utc_iso, so we trigger each occurrence once.
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
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
    path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def _maybe_run_trigger_cmd(cmd_template: str, *, event_id: str, summary: str, meet_url: str, start_utc: str) -> None:
    cmd = (
        cmd_template.replace("{event_id}", event_id)
        .replace("{summary}", summary)
        .replace("{meet_url}", meet_url)
        .replace("{start_utc}", start_utc)
    )
    print(f"  RUN: {cmd}")
    subprocess.run(cmd, shell=True, check=False)


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
    time_min = now_utc
    time_max = now_utc + dt.timedelta(minutes=window_minutes)

    print(f"Calendar ID: {args.calendar}")
    events = calendar.list_upcoming_events(
        calendar_id=args.calendar,
        time_min=time_min,
        time_max=time_max,
        max_results=args.max_results,
    )

    now_local = local_now()
    print(f"Now (local): {now_local.isoformat()}")
    print(f"Now (UTC):   {now_utc.isoformat()}")
    print(f"Looking ahead: {window_minutes} minutes")
    print(f"Found {len(events)} events\n")

    trigger_state_path = _trigger_state_path()
    trigger_state = _load_trigger_state(trigger_state_path)

    for ev in events:
        start_utc = ev.start.astimezone(dt.timezone.utc)
        delta = start_utc - now_utc
        start_local = ev.start.astimezone(now_local.tzinfo)
        minutes_until = int(delta.total_seconds() // 60)

        # Trigger window: from (start - trigger_before) to (start + trigger_after)
        trigger_window_start = start_utc - dt.timedelta(minutes=trigger_before)
        trigger_window_end = start_utc + dt.timedelta(minutes=trigger_after)
        due_now = trigger_window_start <= now_utc <= trigger_window_end

        meet = ev.meet_url or "(no Meet link found)"
        print(f"- {ev.summary}")
        print(f"  start: {start_local.isoformat()} ({minutes_until:+} min)")
        print(f"  meet:  {meet}")

        if ev.meet_url and due_now:
            start_utc_iso = start_utc.isoformat()
            already = trigger_state.get(ev.id) == start_utc_iso
            if not already:
                print(
                    f"  TRIGGER: within window "
                    f"[-{trigger_before}m, +{trigger_after}m] around start"
                )
                trigger_state[ev.id] = start_utc_iso
                _save_trigger_state(trigger_state_path, trigger_state)

                if args.nylas_notetaker:
                    # Create immediately; omit join_time so Notetaker joins now.
                    result = create_notetaker(
                        meeting_link=ev.meet_url,
                        api_key=args.nylas_api_key,
                        api_base=args.nylas_api_base,
                        grant_id=args.nylas_grant_id,
                        name=args.nylas_notetaker_name,
                        meeting_settings={
                            "transcription": True,
                            "audio_recording": True,
                        },
                    )
                    print(f"  NYLAS: created notetaker id={result.id or '(unknown)'}")

                if args.on_trigger_cmd:
                    _maybe_run_trigger_cmd(
                        args.on_trigger_cmd,
                        event_id=ev.id,
                        summary=ev.summary,
                        meet_url=ev.meet_url,
                        start_utc=start_utc_iso,
                    )
            else:
                print("  (already triggered)")

        print("")

    return 0


def main() -> int:
    args = build_parser().parse_args()

    if args.poll_seconds and args.poll_seconds > 0:
        while True:
            run_once(args)
            time.sleep(args.poll_seconds)

    return run_once(args)


if __name__ == "__main__":
    raise SystemExit(main())
