from __future__ import annotations

import argparse
import json
import os
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agents.chunk_extractor_node import extract_facts_from_smart_chunk_via_langchain_tools


@dataclass(frozen=True)
class _OneChunk:
    id: str
    meeting_id: str
    chunk_index: int
    date: datetime
    speaker: str | None
    chunk_content: str
    source: str


def _state_dir() -> Path:
    # Simple local storage for now.
    # Can be overridden for deployments, tests, or different machines.
    return Path(os.environ.get("SMARTMEETOS_STATE_DIR", ".smartmeetos_state")).resolve()


def _write_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Extract facts from ONE chunk and insert into DB via tool-calling.")
    p.add_argument("--input", required=True, help="Path to a UTF-8 text file containing ONE chunk.")
    p.add_argument("--meeting-id", required=True, help="Meeting UUID (meetings.id). Required for DB inserts.")
    p.add_argument("--source-chunk-id", default=None, help="Optional transcript_chunks.id UUID. If omitted, a new UUID is generated.")
    p.add_argument("--chunk-index", type=int, default=0, help="transcript_chunks.chunk_index (default: 0).")
    p.add_argument("--speaker", default=None, help="Optional speaker for this chunk.")
    p.add_argument(
        "--source",
        default="Google Meet",
        choices=["Google Meet", "Zoom", "Microsoft Teams"],
        help='Meeting source label (DB enum value). Example: "Google Meet".',
    )
    p.add_argument(
        "--out-dir",
        default=str(_state_dir() / "extracted_facts"),
        help="Output directory for JSONL records (default: SMARTMEETOS_STATE_DIR/extracted_facts).",
    )

    args = p.parse_args(argv)

    input_path = Path(args.input)
    out_dir = Path(args.out_dir)

    chunk_text = input_path.read_text(encoding="utf-8")

    chunk_id = args.source_chunk_id or str(uuid.uuid4())
    chunk = _OneChunk(
        id=str(chunk_id),
        meeting_id=str(args.meeting_id),
        chunk_index=int(args.chunk_index),
        date=datetime.now(timezone.utc),
        speaker=args.speaker,
        chunk_content=chunk_text,
        source=str(args.source),
    )

    record = extract_facts_from_smart_chunk_via_langchain_tools(chunk, meeting_id=str(args.meeting_id))

    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"extracted_facts_{input_path.stem}_{int(time.time())}.jsonl"
    _write_jsonl(out_file, record)
    print(str(out_file))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
