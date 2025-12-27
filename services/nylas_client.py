from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from smartmeetos.notetaker.nylas_notetaker import create_notetaker
from smartmeetos.notetaker.supervisor import SupervisorConfig, supervise_meeting
from smartmeetos.notetaker.transcript_merge import merge_all_meetings_in_dir, merge_transcripts_for_meeting


@dataclass(frozen=True)
class RunConfig:
    """High-level config for running a meeting via Nylas Notetaker."""

    grant_id: str
    api_key: str | None = None
    api_base: str | None = None
    notetaker_name: str = "Nylas Notetaker"


def create_notetaker_for_meet(*, meet_url: str, cfg: RunConfig) -> dict:
    """Create a Notetaker for a Google Meet URL.

    Returns the raw Nylas response object (dict) produced by `smartmeetos.notetaker.nylas_notetaker`.
    """

    return create_notetaker(
        meeting_url=meet_url,
        grant_id=cfg.grant_id,
        api_key=cfg.api_key,
        api_base=cfg.api_base,
        name=cfg.notetaker_name,
    )


def supervise_meet_recording(
    *,
    meet_url: str,
    event_id: str,
    event_start_utc_iso: str,
    event_end_utc_iso: str,
    cfg: RunConfig,
    supervisor_cfg: SupervisorConfig | None = None,
):
    """Run the robust join/rejoin supervisor for a scheduled meeting."""

    return supervise_meeting(
        meeting_url=meet_url,
        event_id=event_id,
        event_start_utc_iso=event_start_utc_iso,
        event_end_utc_iso=event_end_utc_iso,
        grant_id=cfg.grant_id,
        api_key=cfg.api_key,
        api_base=cfg.api_base,
        notetaker_name=cfg.notetaker_name,
        cfg=supervisor_cfg or SupervisorConfig(),
    )


def merge_transcripts_for_event(
    *,
    transcripts_dir: str | Path,
    event_id: str,
    event_start_utc_iso: str,
    force: bool = False,
) -> tuple[Path | None, Path | None]:
    """Merge transcript fragments (multiple notetaker ids) into one output."""

    td = Path(transcripts_dir)
    return merge_transcripts_for_meeting(
        transcripts_dir=td,
        event_id=event_id,
        event_start=event_start_utc_iso,
        force=force,
    )


def merge_all_transcripts(*, transcripts_dir: str | Path, force: bool = False):
    """Merge all meetings found under a transcripts directory."""

    return merge_all_meetings_in_dir(transcripts_dir=Path(transcripts_dir), force=force)
