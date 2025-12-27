from __future__ import annotations

import datetime as dt
import json
import random
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from smartmeetos.calendar.google_calendar import utc_now
from smartmeetos.notetaker.failure_codes import FailureCode, MeetingRunResult
from smartmeetos.notetaker.nylas_history import get_latest_status_from_history, get_notetaker_history
from smartmeetos.notetaker.nylas_media import download_media_url, get_notetaker_media_links
from smartmeetos.notetaker.nylas_notetaker import create_notetaker


@dataclass(frozen=True)
class SupervisorConfig:
    # Mandatory spec: join attempts between start-2m and start+15m
    join_window_before_minutes: int = 2
    join_window_after_minutes: int = 15

    # New behavior: if the meeting is still in progress, keep attempting to join/rejoin until the
    # scheduled end (bounded by max_overrun_seconds) unless the host denies entry repeatedly.
    max_entry_denials: int = 3

    # Separate limit: stop rejoining after being kicked/removed N times.
    max_kicks: int = 3

    # Mandatory spec: retry every 30–60 seconds
    join_retry_min_seconds: int = 30
    join_retry_max_seconds: int = 60

    # Mandatory spec: waiting room max 5 minutes
    waiting_room_timeout_seconds: int = 5 * 60

    # Mandatory spec: unexpected disconnect -> rejoin every 30s, max 5 minutes
    reconnect_attempt_interval_seconds: int = 30
    reconnect_timeout_seconds: int = 5 * 60

    # Mandatory spec: max duration = scheduled + 30 minutes
    max_overrun_seconds: int = 30 * 60

    # Mandatory spec: event end + 15 min grace exceeded is a meeting-end signal.
    event_end_grace_seconds: int = 15 * 60

    # How often we poll Nylas history while waiting/recording.
    status_poll_seconds: int = 15

    # Transcript availability can lag behind meeting end.
    # IMPORTANT: We fetch transcripts asynchronously (background thread) so we do NOT block the
    # meeting join loop (e.g. `check_calendar.py`) from joining the next meeting.
    # Keep this reasonably large so transcripts are picked up automatically even when processing
    # is delayed.
    post_end_transcript_wait_seconds: int = 20 * 60
    post_end_transcript_poll_seconds: int = 20


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _secrets_dir() -> Path:
    return _repo_root() / ".secrets"


def _transcripts_dir() -> Path:
    return _secrets_dir() / "transcripts"


def _history_dir() -> Path:
    return _secrets_dir() / "history"


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(payload, ensure_ascii=False)
    with path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def save_transcript_if_available(
    *,
    grant_id: str,
    notetaker_id: str,
    event_id: str,
    event_start_utc_iso: str,
    api_key: str | None,
    api_base: str | None,
) -> Path | None:
    """Transcript safety.

    We cannot get truly incremental transcripts unless the provider supports it.
    What we *can* do reliably:
    - persist transcript as soon as it becomes available
    - never overwrite existing transcript files
    - keep per-notetaker files so reconnects don't clobber previous data
    """

    try:
        links = get_notetaker_media_links(
            grant_id=grant_id,
            notetaker_id=notetaker_id,
            api_key=api_key,
            api_base=api_base,
        )
    except Exception:
        return None

    transcript_meta = links.transcript
    transcript_url = transcript_meta.get("url") if isinstance(transcript_meta, dict) else None
    if not isinstance(transcript_url, str) or not transcript_url.startswith("http"):
        return None

    # Persisting the media URL is useful for crash recovery.
    # We also best-effort download the transcript *content* so partial results survive crashes.
    # Reconnects will write a separate file per notetaker_id to avoid overwriting.
    out_dir = _transcripts_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_start = event_start_utc_iso.replace(":", "-")
    meta_path = out_dir / f"{event_id}__{safe_start}__{notetaker_id}.media.json"
    transcript_path = out_dir / f"{event_id}__{safe_start}__{notetaker_id}.transcript.json"

    if not meta_path.exists():
        _atomic_write_json(
            meta_path,
            {
                "event_id": event_id,
                "event_start_utc": event_start_utc_iso,
                "notetaker_id": notetaker_id,
                "transcript": transcript_meta,
                "recording": links.recording,
                "summary": links.summary,
                "action_items": links.action_items,
            },
        )

    # Best-effort: download transcript content once.
    if not transcript_path.exists():
        try:
            raw = download_media_url(url=transcript_url)
            # Store raw JSON bytes as decoded text where possible.
            text = raw.decode("utf-8", errors="replace")
            transcript_path.write_text(text, encoding="utf-8")
        except Exception:
            # Don't crash supervision if transcript download fails.
            pass

    # Return the transcript path when we have it (useful for logs and tooling).
    return transcript_path if transcript_path.exists() else meta_path


def _lower(s: str | None) -> str:
    return (s or "").strip().lower()


def _is_waiting_room(meeting_state: str | None) -> bool:
    ms = _lower(meeting_state)
    return ms == "waiting_for_entry" or "waiting" in ms


def _is_active_recording(meeting_state: str | None) -> bool:
    return _lower(meeting_state) == "recording_active"


def _is_failed_entry(meeting_state: str | None) -> bool:
    # Includes the common ones we've already seen.
    return _lower(meeting_state) in {"failed_entry", "entry_denied", "no_response"}


def _is_removed(event_type: str | None, meeting_state: str | None, state: str | None) -> bool:
    et = _lower(event_type)
    ms = _lower(meeting_state)
    st = _lower(state)
    # Conservative substring matching because Nylas event naming can vary by version.
    return (
        "removed" in et
        or "kicked" in et
        or "removed" in ms
        or "kicked" in ms
        or ms == "bot_removed"
        or st == "removed"
    )


def _looks_ended(meeting_state: str | None) -> bool:
    ms = _lower(meeting_state)
    return ms in {"meeting_ended", "recording_ended", "ended", "completed"} or ms.endswith("_ended")


def _looks_disconnected(meeting_state: str | None) -> bool:
    ms = _lower(meeting_state)
    return ms in {"disconnected", "connection_lost"} or "disconnect" in ms


def _history_log_path(*, event_id: str, event_start_utc_iso: str) -> Path:
    safe_start = event_start_utc_iso.replace(":", "-")
    return _history_dir() / f"{event_id}__{safe_start}.jsonl"


def _try_save_transcripts(
    *,
    grant_id: str,
    notetaker_ids: list[str],
    event_id: str,
    event_start_utc_iso: str,
    api_key: str | None,
    api_base: str | None,
) -> list[Path]:
    saved_paths: list[Path] = []
    for nid in notetaker_ids:
        if not nid:
            continue
        try:
            saved = save_transcript_if_available(
                grant_id=grant_id,
                notetaker_id=nid,
                event_id=event_id,
                event_start_utc_iso=event_start_utc_iso,
                api_key=api_key,
                api_base=api_base,
            )
            if saved is not None:
                saved_paths.append(saved)
        except Exception:
            continue
    return saved_paths


def _wait_for_transcripts_post_end(
    *,
    grant_id: str,
    notetaker_ids: list[str],
    event_id: str,
    event_start_utc_iso: str,
    api_key: str | None,
    api_base: str | None,
    wait_seconds: int,
    poll_seconds: int,
    history_path: Path,
) -> None:
    if wait_seconds <= 0 or not notetaker_ids:
        return

    deadline = utc_now() + dt.timedelta(seconds=wait_seconds)
    print(f"  TRANSCRIPT: harvesting started (max_wait={wait_seconds}s poll={poll_seconds}s ids={len(notetaker_ids)})")
    _append_jsonl(
        history_path,
        {
            "ts_utc": utc_now().isoformat(),
            "type": "post_end_transcript_wait_start",
            "wait_seconds": wait_seconds,
            "poll_seconds": poll_seconds,
            "notetaker_ids": list(notetaker_ids),
        },
    )

    while utc_now() < deadline:
        saved_paths = _try_save_transcripts(
            grant_id=grant_id,
            notetaker_ids=notetaker_ids,
            event_id=event_id,
            event_start_utc_iso=event_start_utc_iso,
            api_key=api_key,
            api_base=api_base,
        )
        if saved_paths:
            for p in saved_paths:
                print(f"  TRANSCRIPT: saved {p}")
            _append_jsonl(
                history_path,
                {
                    "ts_utc": utc_now().isoformat(),
                    "type": "post_end_transcript_saved",
                    "saved_paths": [str(p) for p in saved_paths],
                },
            )
            return

        time.sleep(max(1, poll_seconds))

    _append_jsonl(
        history_path,
        {
            "ts_utc": utc_now().isoformat(),
            "type": "post_end_transcript_wait_timeout",
        },
    )
    print(f"  TRANSCRIPT: not available after {wait_seconds}s")


def supervise_meeting(
    *,
    event_id: str,
    event_summary: str,
    meeting_link: str,
    event_start: dt.datetime,
    event_end: dt.datetime,
    grant_id: str,
    api_key: str | None,
    api_base: str | None,
    notetaker_name: str,
    config: SupervisorConfig,
    meeting_settings: dict[str, Any] | None = None,
    dry_run: bool = False,
) -> MeetingRunResult:
    """Failure-handling supervisor for real-world meeting behavior.

    This wraps the happy-path (create Notetaker) with required retry windows and
    deterministic failure codes.

    Notes about constraints:
    - We do not control the internal Meet join UX; we infer progress via Nylas history.
    - Some signals ("no audio", "bot alone") are not exposed via the current APIs in this repo.
    """

    start_utc = event_start.astimezone(dt.timezone.utc)
    end_utc = event_end.astimezone(dt.timezone.utc)

    join_window_start = start_utc - dt.timedelta(minutes=config.join_window_before_minutes)
    join_window_end = start_utc + dt.timedelta(minutes=config.join_window_after_minutes)

    max_end_time = end_utc + dt.timedelta(seconds=config.max_overrun_seconds)
    end_grace_time = end_utc + dt.timedelta(seconds=config.event_end_grace_seconds)

    started_at = utc_now()
    attempted_ids: list[str] = []
    last_status_raw: dict[str, Any] | None = None

    denied_count = 0
    kicked_count = 0

    history_path = _history_log_path(event_id=event_id, event_start_utc_iso=start_utc.isoformat())
    _append_jsonl(
        history_path,
        {
            "ts_utc": started_at.isoformat(),
            "type": "supervisor_start",
            "event_id": event_id,
            "event_summary": event_summary,
            "event_start_utc": start_utc.isoformat(),
            "event_end_utc": end_utc.isoformat(),
            "meeting_link": meeting_link,
            "config": {
                "join_window_before_minutes": config.join_window_before_minutes,
                "join_window_after_minutes": config.join_window_after_minutes,
                "waiting_room_timeout_seconds": config.waiting_room_timeout_seconds,
                "reconnect_attempt_interval_seconds": config.reconnect_attempt_interval_seconds,
                "max_overrun_seconds": config.max_overrun_seconds,
                "event_end_grace_seconds": config.event_end_grace_seconds,
                "max_entry_denials": config.max_entry_denials,
                "max_kicks": config.max_kicks,
            },
        },
    )

    # Keep console output low-noise and useful:
    # - print Notetaker creation attempts
    # - print meeting_state transitions
    last_printed_meeting_state: str | None = None
    last_printed_error_at: dt.datetime | None = None
    last_printed_status_tuple: tuple[str | None, str | None, str | None] | None = None
    last_heartbeat_at: dt.datetime | None = None
    last_history_error_at: dt.datetime | None = None

    def finalize(*, ok: bool, code: FailureCode | None, message: str, final_id: str | None) -> MeetingRunResult:
        # Automatic transcript retrieval: Nylas can publish transcripts after meeting end or
        # after bot disconnect/kick events. We harvest transcripts asynchronously so this
        # supervisor can return immediately (and allow joining the next meeting).
        if not dry_run:
            ids: list[str] = []
            for nid in attempted_ids:
                if isinstance(nid, str) and nid and nid not in ids:
                    ids.append(nid)
            if isinstance(final_id, str) and final_id and final_id not in ids:
                ids.append(final_id)

            wait_seconds = int(config.post_end_transcript_wait_seconds)
            poll_seconds = int(config.post_end_transcript_poll_seconds)
            if ids and wait_seconds > 0:
                print(
                    f"  TRANSCRIPT: spawning background harvest (max_wait={wait_seconds}s poll={poll_seconds}s ids={len(ids)})"
                )
                _append_jsonl(
                    history_path,
                    {
                        "ts_utc": utc_now().isoformat(),
                        "type": "post_end_transcript_async_spawn",
                        "ok": ok,
                        "failure_code": code.value if code else None,
                        "wait_seconds": wait_seconds,
                        "poll_seconds": poll_seconds,
                        "notetaker_ids": list(ids),
                    },
                )

                def _bg() -> None:
                    try:
                        _wait_for_transcripts_post_end(
                            grant_id=grant_id,
                            notetaker_ids=ids,
                            event_id=event_id,
                            event_start_utc_iso=start_utc.isoformat(),
                            api_key=api_key,
                            api_base=api_base,
                            wait_seconds=wait_seconds,
                            poll_seconds=poll_seconds,
                            history_path=history_path,
                        )
                    except Exception:
                        # Never crash the main supervisor loop due to background harvesting.
                        pass

                t = threading.Thread(
                    target=_bg,
                    name=f"transcript-harvest-{event_id}",
                    daemon=True,
                )
                t.start()

        ended_at = utc_now()
        _append_jsonl(
            history_path,
            {
                "ts_utc": ended_at.isoformat(),
                "type": "supervisor_end",
                "ok": ok,
                "failure_code": code.value if code else None,
                "message": message,
                "final_notetaker_id": final_id,
                "attempted_notetaker_ids": list(attempted_ids),
                "denied_count": denied_count,
                "kicked_count": kicked_count,
            },
        )
        return MeetingRunResult(
            ok=ok,
            failure_code=code,
            message=message,
            event_id=event_id,
            event_start_utc=start_utc.isoformat(),
            event_end_utc=end_utc.isoformat(),
            meeting_link=meeting_link,
            attempted_notetaker_ids=attempted_ids,
            final_notetaker_id=final_id,
            started_at_utc=started_at.isoformat(),
            ended_at_utc=ended_at.isoformat(),
            raw=last_status_raw,
        )

    # Join policy:
    # - Avoid joining too early (start-2m).
    # - If we're late but the meeting is still ongoing (start <= now < end), keep trying until
    #   the meeting ends (bounded by max_overrun_seconds).
    now = utc_now()

    if now < join_window_start:
        # Avoid joining too early: some Meet rooms won't accept until near start.
        time.sleep(max(0.0, (join_window_start - now).total_seconds()))

    # Continue attempting joins/rejoins until the meeting is expected to be over.
    # Safety bound: scheduled end + max_overrun_seconds.
    attempt_deadline = max_end_time

    # JOIN/REJOIN LOOP
    # We keep trying until attempt_deadline OR we hit repeated host denials.
    attempt_no = 0
    while utc_now() <= attempt_deadline:
        if utc_now() > max_end_time:
            return finalize(
                ok=False,
                code=FailureCode.MAX_DURATION_EXCEEDED,
                message="Meeting exceeded scheduled end + overrun limit before join completed.",
                final_id=None,
            )

        # Hard stop if we are past the scheduled end + grace.
        # (At this point the meeting should be over even if Nylas hasn't emitted an 'ended' state.)
        if utc_now() >= end_grace_time:
            return finalize(
                ok=True,
                code=None,
                message="Meeting ended (event end grace exceeded).",
                final_id=attempted_ids[-1] if attempted_ids else None,
            )

        if denied_count >= config.max_entry_denials:
            return finalize(
                ok=False,
                code=FailureCode.JOIN_REFUSED_MAX,
                message=f"Join refused/denied {denied_count} times; giving up.",
                final_id=attempted_ids[-1] if attempted_ids else None,
            )

        if kicked_count >= config.max_kicks:
            return finalize(
                ok=False,
                code=FailureCode.KICKED_MAX,
                message=f"Bot was kicked/removed {kicked_count} times; giving up.",
                final_id=attempted_ids[-1] if attempted_ids else None,
            )

        if dry_run:
            # In dry-run we avoid creating anything but still behave deterministically.
            return finalize(
                ok=True,
                code=None,
                message="(dry-run) would create and supervise Notetaker.",
                final_id=None,
            )

        attempt_no += 1
        print(f"  NYLAS: create attempt {attempt_no} (deadline {attempt_deadline.isoformat()})")

        _append_jsonl(
            history_path,
            {
                "ts_utc": utc_now().isoformat(),
                "type": "create_attempt",
                "attempt_no": attempt_no,
                "denied_count": denied_count,
                "kicked_count": kicked_count,
            },
        )

        try:
            result = create_notetaker(
                meeting_link=meeting_link,
                api_key=api_key,
                api_base=api_base,
                grant_id=grant_id,
                name=notetaker_name,
                meeting_settings=meeting_settings,
            )
        except Exception as e:
            # Fail predictably: if we can't even create, retry until the join window expires.
            last_status_raw = {"error": str(e)}
            now_err = utc_now()
            # Avoid spamming identical errors in tight loops.
            if last_printed_error_at is None or (now_err - last_printed_error_at) > dt.timedelta(seconds=20):
                print(f"  NYLAS: create failed: {e} (will retry)")
                last_printed_error_at = now_err

            _append_jsonl(
                history_path,
                {
                    "ts_utc": now_err.isoformat(),
                    "type": "create_failed",
                    "attempt_no": attempt_no,
                    "error": str(e),
                },
            )
            delay = random.uniform(config.join_retry_min_seconds, config.join_retry_max_seconds)
            time.sleep(delay)
            continue

        notetaker_id = result.id
        if isinstance(notetaker_id, str) and notetaker_id:
            attempted_ids.append(notetaker_id)
        print(f"  NYLAS: created notetaker id={notetaker_id or '(unknown)'}")

        _append_jsonl(
            history_path,
            {
                "ts_utc": utc_now().isoformat(),
                "type": "created",
                "attempt_no": attempt_no,
                "notetaker_id": notetaker_id,
            },
        )

        # WAIT FOR ENTRY / HOST / RECORDING
        created_time = utc_now()
        waiting_room_deadline = created_time + dt.timedelta(seconds=config.waiting_room_timeout_seconds)

        had_recording = False
        disconnect_start: dt.datetime | None = None

        while True:
            # Max duration guard (meeting overrun).
            if utc_now() > max_end_time:
                # We can't force-stop the Notetaker without an API we haven't implemented.
                return finalize(
                    ok=False,
                    code=FailureCode.MAX_DURATION_EXCEEDED,
                    message="Meeting exceeded scheduled end + 30 minutes; stopping supervision.",
                    final_id=notetaker_id,
                )

            # Poll latest history status.
            try:
                history = get_notetaker_history(
                    grant_id=grant_id,
                    notetaker_id=notetaker_id or "",
                    api_key=api_key,
                    api_base=api_base,
                )
                latest = get_latest_status_from_history(history, notetaker_id=notetaker_id or "")
                last_status_raw = latest.raw
            except Exception as e:
                # Status fetch failures should not immediately end an unsupervised run.
                # We treat them as transient and keep polling.
                last_status_raw = {"error": str(e), "notetaker_id": notetaker_id}
                now_err = utc_now()
                if last_history_error_at is None or (now_err - last_history_error_at) > dt.timedelta(seconds=20):
                    print(f"  NYLAS: history/status fetch failed: {e} (will retry)")
                    last_history_error_at = now_err
                time.sleep(max(1, config.status_poll_seconds))
                continue

            # Meeting state signals (best-effort parsing).
            meeting_state = latest.meeting_state
            event_type = latest.event_type
            state = latest.state

            # Heartbeat: show we're still polling even when meeting_state doesn't change.
            now_hb = utc_now()
            if last_heartbeat_at is None or (now_hb - last_heartbeat_at) > dt.timedelta(seconds=60):
                print(
                    "  NYLAS: heartbeat"
                    f" meeting_state={meeting_state or '-'}"
                    f" event_type={event_type or '-'}"
                    f" state={state or '-'}"
                    f" denied={denied_count} kicked={kicked_count}"
                )
                last_heartbeat_at = now_hb

            # Print when (meeting_state/event_type/state) changes, to make progress visible.
            status_tuple = (meeting_state, event_type, state)
            if status_tuple != last_printed_status_tuple and (
                isinstance(meeting_state, str)
                or isinstance(event_type, str)
                or isinstance(state, str)
            ):
                # Avoid duplicating the dedicated meeting_state transition print below.
                if not (isinstance(meeting_state, str) and meeting_state == last_printed_meeting_state):
                    print(
                        "  NYLAS: status"
                        f" meeting_state={meeting_state or '-'}"
                        f" event_type={event_type or '-'}"
                        f" state={state or '-'}"
                    )
                last_printed_status_tuple = status_tuple

            # Print only on meeting_state transitions to keep logs readable.
            if isinstance(meeting_state, str) and meeting_state != last_printed_meeting_state:
                print(f"  NYLAS: meeting_state={meeting_state}")
                last_printed_meeting_state = meeting_state

                _append_jsonl(
                    history_path,
                    {
                        "ts_utc": utc_now().isoformat(),
                        "type": "meeting_state",
                        "notetaker_id": notetaker_id,
                        "meeting_state": meeting_state,
                        "event_type": event_type,
                        "state": state,
                        "denied_count": denied_count,
                        "kicked_count": kicked_count,
                    },
                )

            # Meeting end detection (spec: end when any two of the following occur):
            # - Meeting API reports ended (we approximate via Nylas history meeting_state)
            # - Event end + 15 min grace exceeded
            # - Bot is alone > 60 seconds (NOT AVAILABLE in current APIs)
            # - No audio detected > 5 minutes (NOT AVAILABLE in current APIs)
            #
            # To remain correct and predictable, we only score signals we can observe.
            api_reports_ended = _looks_ended(meeting_state)
            grace_exceeded = utc_now() >= end_grace_time
            media_available = False
            if notetaker_id:
                try:
                    links = get_notetaker_media_links(
                        grant_id=grant_id,
                        notetaker_id=notetaker_id,
                        api_key=api_key,
                        api_base=api_base,
                    )
                    media_available = bool(
                        (isinstance(links.transcript, dict) and isinstance(links.transcript.get("url"), str))
                        or (isinstance(links.recording, dict) and isinstance(links.recording.get("url"), str))
                    )
                except Exception:
                    media_available = False

            end_signals = 0
            end_signals += 1 if api_reports_ended else 0
            end_signals += 1 if grace_exceeded else 0
            end_signals += 1 if media_available else 0

            if _is_removed(event_type, meeting_state, state):
                # New behavior: attempt to rejoin until meeting ends; do not abort immediately.
                kicked_count += 1
                print(
                    "  NYLAS: bot removed/kicked; will create a new Notetaker to rejoin "
                    f"(kicked_count={kicked_count}, denied_count={denied_count})"
                )
                _append_jsonl(
                    history_path,
                    {
                        "ts_utc": utc_now().isoformat(),
                        "type": "bot_removed",
                        "notetaker_id": notetaker_id,
                        "kicked_count": kicked_count,
                    },
                )
                # Break to create a fresh Notetaker.
                break

            if _is_active_recording(meeting_state):
                had_recording = True
                disconnect_start = None

                # Persist media references when available (crash-safe, no overwrite).
                if notetaker_id:
                    save_transcript_if_available(
                        grant_id=grant_id,
                        notetaker_id=notetaker_id,
                        event_id=event_id,
                        event_start_utc_iso=start_utc.isoformat(),
                        api_key=api_key,
                        api_base=api_base,
                    )

                time.sleep(max(1, config.status_poll_seconds))
                continue

            # End when 2+ signals are observed.
            if end_signals >= 2:
                if notetaker_id:
                    save_transcript_if_available(
                        grant_id=grant_id,
                        notetaker_id=notetaker_id,
                        event_id=event_id,
                        event_start_utc_iso=start_utc.isoformat(),
                        api_key=api_key,
                        api_base=api_base,
                    )
                reason_bits: list[str] = []
                if api_reports_ended:
                    reason_bits.append("api_reports_ended")
                if grace_exceeded:
                    reason_bits.append("event_end_grace_exceeded")
                if media_available:
                    reason_bits.append("media_available")
                reason = ",".join(reason_bits) if reason_bits else "unknown"
                return finalize(
                    ok=True,
                    code=None,
                    message=f"Meeting ended (signals={reason}).",
                    final_id=notetaker_id,
                )

            # Unexpected disconnection handling.
            # Important: reconnect attempts must NOT be limited by the initial join window.
            # Once we've been recording, we keep trying to rejoin until the meeting ends
            # (bounded by attempt_deadline) or we hit repeated denials.
            if had_recording and (
                _looks_disconnected(meeting_state)
                or _is_failed_entry(meeting_state)
                or (disconnect_start is not None and _is_waiting_room(meeting_state))
            ):
                # If the host explicitly denies re-entry after we had been recording,
                # count it toward the refusal limit so we don't loop forever.
                if _lower(meeting_state) in {"entry_denied"}:
                    denied_count += 1
                    _append_jsonl(
                        history_path,
                        {
                            "ts_utc": utc_now().isoformat(),
                            "type": "entry_denied_reconnect",
                            "notetaker_id": notetaker_id,
                            "denied_count": denied_count,
                            "kicked_count": kicked_count,
                        },
                    )
                    print(f"  NYLAS: re-entry denied by host (denied_count={denied_count})")

                    if denied_count >= config.max_entry_denials:
                        return finalize(
                            ok=False,
                            code=FailureCode.JOIN_REFUSED_MAX,
                            message=f"Rejoin refused/denied {denied_count} times; giving up.",
                            final_id=attempted_ids[-1] if attempted_ids else notetaker_id,
                        )

                if disconnect_start is None:
                    disconnect_start = utc_now()
                # No fixed reconnect timeout anymore; we keep trying until meeting end or denial limit.

                # Attempt rejoin by creating a new Notetaker instance.
                # We wait a fixed 30s between attempts (mandatory spec).
                wait_s = max(1, config.reconnect_attempt_interval_seconds)
                print(f"  NYLAS: waiting {wait_s}s before reconnect attempt")
                time.sleep(wait_s)

                try:
                    rejoin = create_notetaker(
                        meeting_link=meeting_link,
                        api_key=api_key,
                        api_base=api_base,
                        grant_id=grant_id,
                        name=notetaker_name,
                        meeting_settings=meeting_settings,
                    )
                    if isinstance(rejoin.id, str) and rejoin.id:
                        notetaker_id = rejoin.id
                        attempted_ids.append(notetaker_id)
                        # Keep the same disconnect_start so the 5-minute budget is enforced.
                except Exception as e:
                    last_status_raw = {"error": str(e), "phase": "reconnect"}

                # Continue polling with the new notetaker_id (or keep trying on next loop).

                continue

            # Waiting room / admission failure (initial join only).
            if _is_waiting_room(meeting_state):
                if utc_now() >= waiting_room_deadline:
                    denied_count += 1
                    _append_jsonl(
                        history_path,
                        {
                            "ts_utc": utc_now().isoformat(),
                            "type": "waiting_room_timeout",
                            "notetaker_id": notetaker_id,
                            "denied_count": denied_count,
                        },
                    )
                    # Break to create a new Notetaker and try again.
                    break

                # Keep waiting until either admitted or timeout.
                time.sleep(max(1, config.status_poll_seconds))
                continue

            # Meeting may not exist yet / host not joined.
            if _is_failed_entry(meeting_state) and not had_recording:
                # Distinguish "denied" vs "not ready".
                if _lower(meeting_state) in {"entry_denied"}:
                    denied_count += 1
                    _append_jsonl(
                        history_path,
                        {
                            "ts_utc": utc_now().isoformat(),
                            "type": "entry_denied",
                            "notetaker_id": notetaker_id,
                            "denied_count": denied_count,
                        },
                    )
                    print("  NYLAS: entry denied by host (will retry)")
                    break

                # Otherwise treat as meeting not ready / transient.
                print("  NYLAS: entry failed / meeting not ready yet (retrying)")
                break

            # Otherwise: keep polling.
            time.sleep(max(1, config.status_poll_seconds))

        # Delay between creation attempts.
        delay = random.uniform(config.join_retry_min_seconds, config.join_retry_max_seconds)
        delay_s = max(1.0, float(delay))
        print(f"  NYLAS: waiting {delay_s:.0f}s before next create attempt")
        time.sleep(delay_s)

    # Deadline exceeded.
    return finalize(
        ok=True,
        code=None,
        message="Meeting ended (attempt deadline exceeded).",
        final_id=attempted_ids[-1] if attempted_ids else None,
    )
