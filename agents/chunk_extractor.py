from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

from agents.chunk_extractor_node import extract_facts_from_transcript_chunk


def _state_dir() -> Path:
    # Simple local storage for now.
    # Can be overridden for deployments, tests, or different machines.
    return Path(os.environ.get("SMARTMEETOS_STATE_DIR", ".smartmeetos_state")).resolve()


def _write_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Extract facts from transcript text using the Groq API.")
    p.add_argument("--input", required=True, help="Path to a UTF-8 text file containing ONE chunk (already chunked).")
    p.add_argument("--meeting-id", default=None, help="Optional meeting id to include in output records.")
    p.add_argument("--source-chunk-id", default=None, help="Optional transcript_chunks.id (UUID) for DB writes.")
    p.add_argument("--chunk-index", type=int, default=None, help="Optional transcript_chunks.chunk_index.")
    p.add_argument("--speaker", default=None, help="Optional speaker for this chunk.")
    p.add_argument(
        "--out-dir",
        default=str(_state_dir() / "extracted_facts"),
        help="Output directory for JSONL records (default: SMARTMEETOS_STATE_DIR/extracted_facts).",
    )

    args = p.parse_args(argv)

    input_path = Path(args.input)
    out_dir = Path(args.out_dir)

    chunk_text = input_path.read_text(encoding="utf-8")
    record = extract_facts_from_transcript_chunk(
        chunk_text=chunk_text,
        meeting_id=args.meeting_id,
        source_chunk_id=args.source_chunk_id,
        chunk_index=args.chunk_index,
        speaker=args.speaker,
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"extracted_facts_{input_path.stem}_{int(time.time())}.jsonl"
    _write_jsonl(out_file, record)
    print(str(out_file))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
