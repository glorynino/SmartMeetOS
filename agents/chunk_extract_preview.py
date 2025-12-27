from __future__ import annotations

import argparse
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from agents.chunk_extractor_node import extract_facts_from_smart_chunk
from processing.smart_chunker_node import smart_chunk_transcript


MEETING_SOURCE_VALUES: dict[str, str] = {
    "google_meet": "Google Meet",
    "zoom": "Zoom",
    "microsoft_teams": "Microsoft Teams",
}


def _print_human(chunk_index: int, chunk_id: str, speaker: str | None, chunk_content: str, facts: list[dict[str, Any]]) -> None:
    print(f"\n--- chunk_index={chunk_index} id={chunk_id} speaker={speaker} ---")
    print(chunk_content.strip())
    if not facts:
        print("(no facts)")
        return

    for f in facts:
        fact_type = f.get("fact_type")
        certainty = f.get("certainty")
        fact_content = f.get("fact_content")
        print(f"- [{fact_type}] {fact_content} (certainty={certainty})")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Preview: Smart Chunker -> Chunk Extractor (Groq) per chunk. Prints to stdout (no JSONL files)."
    )
    p.add_argument("--input", required=True, help="Path to a UTF-8 transcript text file.")
    p.add_argument("--meeting-id", default=None, help="Optional meeting UUID.")
    p.add_argument(
        "--source",
        default="google_meet",
        choices=sorted(MEETING_SOURCE_VALUES.keys()),
        help="Meeting source (maps to MeetingSource enum).",
    )
    p.add_argument("--max-chars", type=int, default=2000)
    p.add_argument("--overlap-chars", type=int, default=200)
    p.add_argument(
        "--max-workers",
        type=int,
        default=int(os.environ.get("EXTRACT_MAX_WORKERS", "4")),
        help="Max parallel chunk extraction workers (default: EXTRACT_MAX_WORKERS or 4).",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON (one object containing chunks + extraction results).",
    )

    args = p.parse_args(argv)

    input_path = Path(args.input)
    transcript_text = input_path.read_text(encoding="utf-8")

    source_value = MEETING_SOURCE_VALUES.get(args.source.strip().lower())
    if not source_value:
        raise ValueError(f"Invalid source '{args.source}'. Use one of: {', '.join(MEETING_SOURCE_VALUES.keys())}")

    chunks = smart_chunk_transcript(
        transcript_text,
        meeting_id=args.meeting_id,
        source=source_value,
        max_chars=args.max_chars,
        overlap_chars=args.overlap_chars,
    )

    max_workers = int(args.max_workers)
    if max_workers <= 0:
        max_workers = 1

    def extract_one(c) -> tuple[int, dict[str, Any]]:
        resp = extract_facts_from_smart_chunk(c, meeting_id=args.meeting_id)
        return c.chunk_index, resp

    results: list[tuple[int, dict[str, Any]]] = []
    if chunks:
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futs = [ex.submit(extract_one, c) for c in chunks]
            for fut in as_completed(futs):
                results.append(fut.result())

    results.sort(key=lambda t: t[0])

    if args.json:
        payload = {
            "meeting_id": args.meeting_id,
            "source": source_value,
            "chunks": [
                {
                    "id": c.id,
                    "meeting_id": c.meeting_id,
                    "chunk_index": c.chunk_index,
                    "date": c.date.isoformat(),
                    "speaker": c.speaker,
                    "chunk_content": c.chunk_content,
                    "source": c.source,
                }
                for c in sorted(chunks, key=lambda x: x.chunk_index)
            ],
            "extractions": [resp for _idx, resp in results],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    print(f"chunks = {len(chunks)}")
    for c in sorted(chunks, key=lambda x: x.chunk_index):
        resp = next((r for idx, r in results if idx == c.chunk_index), None)
        facts = (resp or {}).get("facts", []) or []
        _print_human(c.chunk_index, c.id, c.speaker, c.chunk_content, facts)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
