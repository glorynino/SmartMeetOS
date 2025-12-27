from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


# NOTE: This module is intentionally self-contained and read-only over existing transcript
# fragments. It never mutates or deletes original transcript files.


MERGE_MARKER_TEXT = "[Recording resumed after disconnection]"


@dataclass(frozen=True)
class NormalizedEntry:
    speaker: str | None
    text: str
    timestamp: float | None
    notetaker_id: str
    segment_index: int


def _safe_event_start_token(event_start: str) -> str:
    """Convert ISO-ish event_start into the filename token used by this repo.

    Existing transcript filenames use:
      <event_id>__<event_start_token>__<notetaker_id>.transcript.json

    where event_start_token is typically ISO with ':' replaced by '-'.
    """

    return event_start.replace(":", "-")


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def _atomic_write_json(path: Path, payload: Any) -> None:
    _atomic_write_text(path, json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))


def _file_ctime_seconds(path: Path) -> float:
    # On Windows this is creation time; on Unix it's metadata-change time.
    # We use it only as a fallback ordering key.
    return path.stat().st_ctime


_FILENAME_RE = re.compile(
    r"^(?P<event_id>[^_]+)__(?P<event_start>[^_]+)__(?P<notetaker_id>[^.]+)\\.transcript\\.json$"
)


def list_transcript_files(
    *,
    transcripts_dir: Path,
    event_id: str,
    event_start: str,
) -> list[Path]:
    """Locate transcript fragment files for a meeting key.

    - Ignores MERGED outputs
    - Ignores unrelated files
    """

    if not transcripts_dir.exists():
        return []

    token = _safe_event_start_token(event_start)
    prefix = f"{event_id}__{token}__"

    out: list[Path] = []
    for p in transcripts_dir.iterdir():
        if not p.is_file():
            continue
        name = p.name
        if not name.startswith(prefix):
            continue
        if not name.endswith(".transcript.json"):
            continue
        if "__MERGED." in name:
            continue
        out.append(p)

    # Deterministic file order:
    # - primary: ctime
    # - secondary: filename
    out.sort(key=lambda x: (_file_ctime_seconds(x), x.name))
    return out


def _parse_transcript_payload(raw_text: str) -> Any:
    try:
        return json.loads(raw_text)
    except Exception:
        return raw_text


def _coerce_timestamp(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        # If values look like ms epoch, we *don't* convert (we don't know). We just keep numeric.
        return float(value)
    return None


def _normalize_from_object(
    *,
    obj: Any,
    notetaker_id: str,
    segment_index_start: int,
) -> list[NormalizedEntry]:
    entries: list[NormalizedEntry] = []
    seg = segment_index_start

    # Common Nylas transcript shape we already print:
    # {"object":"transcript","type":"speaker_labelled","transcript":[{"speaker","start","end","text"}, ...]}
    if isinstance(obj, dict):
        t = obj.get("type")
        body = obj.get("transcript")

        if t == "speaker_labelled" and isinstance(body, list):
            for item in body:
                if not isinstance(item, dict):
                    continue
                text = item.get("text")
                if not isinstance(text, str) or not text.strip():
                    continue
                speaker = item.get("speaker")
                start = _coerce_timestamp(item.get("start"))
                entries.append(
                    NormalizedEntry(
                        speaker=speaker.strip() if isinstance(speaker, str) and speaker.strip() else None,
                        text=text.strip(),
                        timestamp=start,
                        notetaker_id=notetaker_id,
                        segment_index=seg,
                    )
                )
                seg += 1
            return entries

        # Raw transcript: {"type":"raw","transcript":"..."}
        if t == "raw" and isinstance(body, str) and body.strip():
            entries.append(
                NormalizedEntry(
                    speaker=None,
                    text=body.strip(),
                    timestamp=None,
                    notetaker_id=notetaker_id,
                    segment_index=seg,
                )
            )
            return entries

        # Fallbacks: if the dict itself looks like a segment.
        text = obj.get("text")
        if isinstance(text, str) and text.strip():
            speaker = obj.get("speaker")
            ts = _coerce_timestamp(obj.get("start_time") or obj.get("timestamp") or obj.get("start"))
            entries.append(
                NormalizedEntry(
                    speaker=speaker.strip() if isinstance(speaker, str) and speaker.strip() else None,
                    text=text.strip(),
                    timestamp=ts,
                    notetaker_id=notetaker_id,
                    segment_index=seg,
                )
            )
            return entries

    # If it is already a list of segments.
    if isinstance(obj, list):
        for item in obj:
            if isinstance(item, dict):
                text = item.get("text")
                if not isinstance(text, str) or not text.strip():
                    continue
                speaker = item.get("speaker")
                ts = _coerce_timestamp(item.get("start_time") or item.get("timestamp") or item.get("start"))
                entries.append(
                    NormalizedEntry(
                        speaker=speaker.strip() if isinstance(speaker, str) and speaker.strip() else None,
                        text=text.strip(),
                        timestamp=ts,
                        notetaker_id=notetaker_id,
                        segment_index=seg,
                    )
                )
                seg += 1
            elif isinstance(item, str) and item.strip():
                entries.append(
                    NormalizedEntry(
                        speaker=None,
                        text=item.strip(),
                        timestamp=None,
                        notetaker_id=notetaker_id,
                        segment_index=seg,
                    )
                )
                seg += 1
        return entries

    # Raw string fallback.
    if isinstance(obj, str) and obj.strip():
        entries.append(
            NormalizedEntry(
                speaker=None,
                text=obj.strip(),
                timestamp=None,
                notetaker_id=notetaker_id,
                segment_index=seg,
            )
        )

    return entries


def normalize_transcript_file(path: Path) -> list[NormalizedEntry]:
    """Load one fragment file and normalize it.

    Missing timestamps are allowed; they will be ordered deterministically via
    segment_index and file ordering.
    """

    m = _FILENAME_RE.match(path.name)
    notetaker_id = m.group("notetaker_id") if m else "unknown"

    raw_text = path.read_text(encoding="utf-8", errors="replace")
    obj = _parse_transcript_payload(raw_text)

    return _normalize_from_object(obj=obj, notetaker_id=notetaker_id, segment_index_start=0)


def _sorted_entries(
    *,
    files: list[Path],
    per_file_entries: list[list[NormalizedEntry]],
) -> list[NormalizedEntry]:
    # Deterministic ordering:
    # 1) timestamp (if present)
    # 2) file order index
    # 3) segment_index
    # 4) file name
    out: list[NormalizedEntry] = []

    for file_index, (p, entries) in enumerate(zip(files, per_file_entries, strict=True)):
        for e in entries:
            # Carry segment_index in a way that preserves file ordering.
            # Segment indexes in fragments restart at 0; we make them globally unique.
            out.append(
                NormalizedEntry(
                    speaker=e.speaker,
                    text=e.text,
                    timestamp=e.timestamp,
                    notetaker_id=e.notetaker_id,
                    segment_index=(file_index * 1_000_000) + e.segment_index,
                )
            )

    def key(e: NormalizedEntry) -> tuple[int, float, int, str]:
        has_ts = 0 if e.timestamp is not None else 1
        ts = e.timestamp if e.timestamp is not None else 0.0
        return (has_ts, ts, e.segment_index, e.notetaker_id)

    out.sort(key=key)
    return out


def _insert_gap_markers(entries: list[NormalizedEntry]) -> list[NormalizedEntry]:
    """Insert a marker if time gap between consecutive timestamped entries > 30 seconds."""

    if not entries:
        return []

    out: list[NormalizedEntry] = []
    prev_ts: float | None = None

    for idx, e in enumerate(entries):
        if prev_ts is not None and e.timestamp is not None:
            if (e.timestamp - prev_ts) > 30.0:
                # Insert marker with a timestamp just after prev_ts to preserve ordering.
                out.append(
                    NormalizedEntry(
                        speaker=None,
                        text=MERGE_MARKER_TEXT,
                        timestamp=prev_ts + 0.0001,
                        notetaker_id="system",
                        segment_index=-1_000_000 + idx,
                    )
                )

        out.append(e)
        if e.timestamp is not None:
            prev_ts = e.timestamp

    # Re-sort to keep deterministic output even with inserted markers.
    out.sort(key=lambda x: (0 if x.timestamp is not None else 1, x.timestamp or 0.0, x.segment_index, x.notetaker_id))
    return out


def merge_transcripts_for_meeting(
    *,
    transcripts_dir: Path,
    event_id: str,
    event_start: str,
    force: bool = False,
) -> tuple[Path | None, Path | None]:
    """Merge all transcript fragments for (event_id, event_start).

    - Never mutates/deletes fragments
    - Idempotent: if merged outputs exist, skips unless force=True
    - Crash-safe: atomic writes

    Returns:
      (merged_json_path, merged_txt_path) or (None, None) if no-op.
    """

    files = list_transcript_files(transcripts_dir=transcripts_dir, event_id=event_id, event_start=event_start)
    if not files:
        return None, None

    token = _safe_event_start_token(event_start)
    merged_json = transcripts_dir / f"{event_id}__{token}__MERGED.transcript.json"
    merged_txt = transcripts_dir / f"{event_id}__{token}__MERGED.txt"

    if not force and merged_json.exists() and merged_txt.exists():
        return merged_json, merged_txt

    per_file_entries: list[list[NormalizedEntry]] = []
    for p in files:
        per_file_entries.append(normalize_transcript_file(p))

    ordered = _sorted_entries(files=files, per_file_entries=per_file_entries)
    ordered = _insert_gap_markers(ordered)

    # JSON output is auditable and includes provenance.
    merged_payload = {
        "object": "merged_transcript",
        "meeting_key": {"event_id": event_id, "event_start": event_start},
        "source_files": [str(p.name) for p in files],
        "entries": [
            {
                "speaker": e.speaker,
                "text": e.text,
                "timestamp": e.timestamp,
                "notetaker_id": e.notetaker_id,
                "segment_index": e.segment_index,
            }
            for e in ordered
        ],
    }

    # Human-readable text output.
    lines: list[str] = []
    for e in ordered:
        if e.text == MERGE_MARKER_TEXT:
            lines.append(MERGE_MARKER_TEXT)
            continue
        if e.speaker:
            lines.append(f"{e.speaker}: {e.text}")
        else:
            lines.append(e.text)

    _atomic_write_json(merged_json, merged_payload)
    _atomic_write_text(merged_txt, "\n".join(lines).strip() + "\n")

    return merged_json, merged_txt


def merge_all_meetings_in_dir(
    *,
    transcripts_dir: Path,
    force: bool = False,
) -> list[tuple[Path, Path]]:
    """Merge all meetings found in a transcript directory.

    Groups by meeting_key=(event_id, event_start_token).
    This is useful when transcripts arrive late/out-of-order.
    """

    if not transcripts_dir.exists():
        return []

    groups: dict[tuple[str, str], list[Path]] = {}
    for p in transcripts_dir.iterdir():
        if not p.is_file():
            continue
        if not p.name.endswith(".transcript.json"):
            continue
        if "__MERGED." in p.name:
            continue
        m = _FILENAME_RE.match(p.name)
        if not m:
            continue
        key = (m.group("event_id"), m.group("event_start"))
        groups.setdefault(key, []).append(p)

    merged: list[tuple[Path, Path]] = []
    for (event_id, event_start_token) in sorted(groups.keys()):
        # We accept event_start_token as-is (already safe token).
        merged_json = transcripts_dir / f"{event_id}__{event_start_token}__MERGED.transcript.json"
        merged_txt = transcripts_dir / f"{event_id}__{event_start_token}__MERGED.txt"
        if not force and merged_json.exists() and merged_txt.exists():
            continue

        # Reuse merge function by passing the token as event_start.
        out_json, out_txt = merge_transcripts_for_meeting(
            transcripts_dir=transcripts_dir,
            event_id=event_id,
            event_start=event_start_token,
            force=force,
        )
        if out_json and out_txt:
            merged.append((out_json, out_txt))

    return merged
