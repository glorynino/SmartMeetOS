from __future__ import annotations

import argparse
import datetime as dt
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


def run_once(args: argparse.Namespace) -> int:
    window_minutes = parse_minutes(args.window_minutes)
    trigger_before = parse_minutes(args.trigger_before_minutes)

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

    for ev in events:
        start_utc = ev.start.astimezone(dt.timezone.utc)
        delta = start_utc - now_utc
        start_local = ev.start.astimezone(now_local.tzinfo)
        minutes_until = int(delta.total_seconds() // 60)

        meet = ev.meet_url or "(no Meet link found)"
        print(f"- {ev.summary}")
        print(f"  start: {start_local.isoformat()} ({minutes_until:+} min)")
        print(f"  meet:  {meet}")

        if ev.meet_url and 0 <= delta.total_seconds() <= trigger_before * 60:
            print(f"  TRIGGER: meeting starts within {trigger_before} minutes")

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
