from __future__ import annotations

import argparse

from smartmeetos.notetaker.nylas_history import get_latest_status_from_history, get_notetaker_history


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Check latest Nylas Notetaker join/meeting status.")
    p.add_argument("--grant-id", required=True, help="Nylas grant id")
    p.add_argument("--notetaker-id", required=True, help="Nylas notetaker id")
    p.add_argument("--nylas-api-key", default=None, help="Nylas API key (or set NYLAS_API_KEY env var)")
    p.add_argument(
        "--nylas-api-base",
        default=None,
        help="Nylas API base URL (default: https://api.us.nylas.com or NYLAS_API_BASE)",
    )
    p.add_argument(
        "--show-events",
        type=int,
        default=0,
        help="If >0, print the N most recent history events (default: 0)",
    )
    return p


def main() -> int:
    args = build_parser().parse_args()

    history = get_notetaker_history(
        grant_id=args.grant_id,
        notetaker_id=args.notetaker_id,
        api_key=args.nylas_api_key,
        api_base=args.nylas_api_base,
    )

    latest = get_latest_status_from_history(history, notetaker_id=args.notetaker_id)

    if args.show_events and args.show_events > 0:
        data = history.get("data") if isinstance(history, dict) else None
        events = data.get("events") if isinstance(data, dict) else None
        if isinstance(events, list) and events:
            print("Most recent history events:")
            for ev in events[: args.show_events]:
                if not isinstance(ev, dict):
                    continue
                event_type = ev.get("event_type")
                created_at = ev.get("created_at")
                obj = ev.get("data") if isinstance(ev.get("data"), dict) else None
                state = obj.get("state") if isinstance(obj, dict) else None
                meeting_state = obj.get("meeting_state") if isinstance(obj, dict) else None
                print(f"- created_at={created_at} event_type={event_type} state={state} meeting_state={meeting_state}")
            print("")

    print(f"notetaker_id:  {latest.notetaker_id}")
    print(f"event_type:    {latest.event_type}")
    print(f"state:         {latest.state}")
    print(f"meeting_state: {latest.meeting_state}")

    # Helpful interpretation
    if latest.meeting_state == "waiting_for_entry":
        print("\nMeaning: the bot is waiting to be admitted in the lobby.")
    elif latest.meeting_state in {"failed_entry", "entry_denied", "no_response"}:
        print("\nMeaning: the bot failed to enter (admission denied/timeout).")
    elif latest.meeting_state in {"recording_active"}:
        print("\nMeaning: the bot is in the meeting and recording.")
    elif latest.meeting_state in {"recording_ended", "meeting_ended", "disconnected"}:
        print("\nMeaning: the bot is no longer in the meeting (ended or disconnected).")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
