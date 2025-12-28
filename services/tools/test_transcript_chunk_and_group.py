from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from agents.groq_llm import groq_chat_json, groq_chat_json_relaxed
from agents.group_and_aggregate_pipeline import run_extracted_facts_to_inputs_jsonl
from processing.smart_chunker_node import smart_chunk_transcript


class TranscriptChunkRow(BaseModel):
    id: str = Field(..., description="UUID string (transcript_chunks.id)")
    meeting_id: str = Field(..., description="UUID string (meetings.id)")
    chunk_index: int
    date: str = Field(..., description="ISO datetime string")
    speaker: str | None = None
    chunk_content: str
    source: str = Field(..., description='Enum value string like "Google Meet"')


class InsertTranscriptChunksArgs(BaseModel):
    rows: list[TranscriptChunkRow]


class ExtractedFactRow(BaseModel):
    meeting_id: str = Field(..., description="UUID string (meetings.id)")
    source_chunk_id: str = Field(..., description="UUID string (transcript_chunks.id)")
    speaker: str | None = None
    fact_type: str = Field(..., description="FactType enum value")
    fact_content: str
    certainty: int = 70
    group_label: str | None = None
    created_at: str = Field(..., description="ISO datetime string")


class InsertExtractedFactsArgs(BaseModel):
    rows: list[ExtractedFactRow]


FACT_TYPE_VALUES: tuple[str, ...] = (
    "statement",
    "proposal",
    "question",
    "decision",
    "action",
    "constraint",
    "agreement",
    "disagreement",
    "clarification",
    "condition",
    "reminder",
)


MEETING_SOURCE_VALUES: dict[str, str] = {
    "google_meet": "Google Meet",
    "zoom": "Zoom",
    "microsoft_teams": "Microsoft Teams",
}


def _state_dir() -> Path:
    return Path(os.environ.get("SMARTMEETOS_STATE_DIR", ".smartmeetos_state")).resolve()


def _load_env_file(path: Path) -> None:
    """Best-effort .env loader (no external dependency).

    Loads KEY=VALUE pairs into os.environ only if KEY is not already set.
    Supports optional single/double quotes around VALUE.
    """

    if not path.exists() or not path.is_file():
        return

    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or key in os.environ:
            continue
        if (value.startswith("\"") and value.endswith("\"")) or (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]
        os.environ[key] = value


def _write_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Local test: transcript file -> smart chunk -> extract facts (LLM) -> group+aggregate (LLM).\n\n"
            "This runner does NOT require a database: it uses in-memory tool stubs in place of DB write tools.\n"
            "Requires: GROQ_API_KEY (and optional GROQ_MODEL)."
        )
    )
    p.add_argument("--input", required=True, help="Path to a UTF-8 transcript text file")
    p.add_argument(
        "--source",
        default="google_meet",
        choices=sorted(MEETING_SOURCE_VALUES.keys()),
        help="Meeting source (affects the chunk.source field)",
    )
    p.add_argument(
        "--meeting-id",
        default=None,
        help="Optional meeting UUID. If omitted, a random UUID will be generated.",
    )
    p.add_argument("--max-chars", type=int, default=2000)
    p.add_argument("--overlap-chars", type=int, default=200)
    p.add_argument(
        "--max-workers",
        type=int,
        default=int(os.environ.get("EXTRACT_MAX_WORKERS", "4")),
        help="Parallel extraction workers (default: EXTRACT_MAX_WORKERS or 4)",
    )
    p.add_argument(
        "--out-dir",
        default=str(_state_dir() / "local_pipeline"),
        help="Output directory for JSONL artifacts (default: SMARTMEETOS_STATE_DIR/local_pipeline)",
    )
    p.add_argument(
        "--max-facts-per-call",
        type=int,
        default=int(os.environ.get("GROUPING_MAX_FACTS_PER_CALL", "30")),
        help="How many facts to label per LLM call (default: GROUPING_MAX_FACTS_PER_CALL or 30)",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    # Convenience: allow running locally with vars stored in repo-root .env.
    _load_env_file(_ROOT / ".env")
    _load_env_file(_ROOT / ".env.local")

    args = build_parser().parse_args(argv)

    input_path = Path(args.input)
    transcript_text = input_path.read_text(encoding="utf-8")

    meeting_id = args.meeting_id or str(uuid.uuid4())
    try:
        _ = uuid.UUID(meeting_id)
    except Exception:
        raise SystemExit(f"--meeting-id must be a UUID string, got: {meeting_id!r}")

    source_value = MEETING_SOURCE_VALUES.get(str(args.source).strip().lower())
    if not source_value:
        raise SystemExit(f"Invalid --source. Choose one of: {', '.join(MEETING_SOURCE_VALUES.keys())}")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    transcript_chunk_rows: list[dict[str, Any]] = []
    extracted_fact_rows: list[dict[str, Any]] = []

    # Chunking (deterministic).
    chunks = smart_chunk_transcript(
        transcript_text,
        meeting_id=meeting_id,
        source=source_value,
        max_chars=int(args.max_chars),
        overlap_chars=int(args.overlap_chars),
    )

    # DB-shaped transcript_chunks rows (for artifact JSONL)
    for c in chunks:
        transcript_chunk_rows.append(
            {
                "id": c.id,
                "meeting_id": c.meeting_id,
                "chunk_index": c.chunk_index,
                "date": c.date.isoformat(),
                "speaker": c.speaker,
                "chunk_content": c.chunk_content,
                "source": c.source,
            }
        )

    created_at = datetime.now(timezone.utc).isoformat()

    def extract_facts_json(*, chunk_id: str, chunk_text: str, speaker: str | None) -> list[dict[str, Any]]:
        """JSON-only extractor for local testing (no tool-calling, no DB)."""

        system = (
            "You extract atomic meeting facts from a transcript chunk. "
            "Return ONLY valid JSON. No markdown, no prose."
        )

        schema_hint = {
            "facts": [
                {
                    "speaker": None,
                    "fact_type": "action",
                    "fact_content": "...",
                    "certainty": 70,
                }
            ]
        }

        user = (
            "Extract at most 12 atomic facts. Prefer action items, decisions, commitments, deadlines, requests, and blockers.\n"
            "Rules:\n"
            "- fact_type MUST be one of: "
            + ", ".join(FACT_TYPE_VALUES)
            + "\n"
            "- certainty MUST be int 0..100\n"
            "- Do not invent details\n"
            "- If no useful facts, return {\"facts\": []}\n\n"
            "chunk_content:\n"
            + chunk_text
            + "\n\nReturn JSON matching this shape: "
            + json.dumps(schema_hint, ensure_ascii=False)
        )

        # Prefer strict JSON mode; fallback to relaxed parsing if needed.
        try:
            data = groq_chat_json(
                messages=[SystemMessage(content=system), HumanMessage(content=user)],
                max_tokens=900,
                temperature=0.0,
            )
        except Exception:
            data = groq_chat_json_relaxed(
                messages=[SystemMessage(content=system), HumanMessage(content=user)],
                max_tokens=900,
                temperature=0.0,
            )

        facts = data.get("facts")
        if not isinstance(facts, list):
            return []

        allowed = set(FACT_TYPE_VALUES)
        out: list[dict[str, Any]] = []
        for item in facts:
            if not isinstance(item, dict):
                continue
            ft = str(item.get("fact_type") or "").strip()
            if ft not in allowed:
                ft = "statement"
            fc = str(item.get("fact_content") or "").strip()
            if not fc:
                continue
            try:
                c = int(item.get("certainty") if item.get("certainty") is not None else 70)
            except Exception:
                c = 70
            c = max(0, min(100, c))
            sp = item.get("speaker")
            if sp is None:
                sp = speaker
            if sp is not None:
                sp = str(sp).strip()
                sp = sp if sp else None

            out.append(
                {
                    "meeting_id": meeting_id,
                    "source_chunk_id": chunk_id,
                    "speaker": sp,
                    "fact_type": ft,
                    "fact_content": fc,
                    "certainty": c,
                    "group_label": None,
                    "created_at": created_at,
                }
            )

        # Hard cap for safety.
        return out[:12]

    # Run extraction for each chunk
    if args.max_workers <= 0:
        args.max_workers = 1

    def extract_one(c) -> list[dict[str, Any]]:
        # Small retry for transient 429/rate limits
        for attempt in range(4):
            try:
                return extract_facts_json(
                    chunk_id=str(getattr(c, "id")),
                    chunk_text=str(getattr(c, "chunk_content")),
                    speaker=getattr(c, "speaker", None),
                )
            except Exception as e:
                msg = str(e)
                if "rate_limit" in msg.lower() or "429" in msg:
                    time.sleep(3)
                    continue
                raise
        return []

    results: list[list[dict[str, Any]]] = []
    if chunks:
        mw = int(args.max_workers)
        ordered = sorted(chunks, key=lambda x: x.chunk_index)
        if mw == 1:
            for idx, c in enumerate(ordered, start=1):
                print(f"extracting chunk {idx}/{len(ordered)} (chunk_index={c.chunk_index})...")
                batch = extract_one(c)
                results.append(batch)
                extracted_fact_rows.extend(batch)
        else:
            with ThreadPoolExecutor(max_workers=mw) as ex:
                futs = [ex.submit(extract_one, c) for c in ordered]
                for fut in as_completed(futs):
                    batch = fut.result()
                    results.append(batch)
                    extracted_fact_rows.extend(batch)

    facts_from_results = sum(len(b) for b in results)

    # Persist artifacts (DB-shaped JSONL) so you can inspect them and/or feed other steps.
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    transcript_chunks_path = out_dir / f"transcript_chunks_{ts}.jsonl"
    extracted_facts_path = out_dir / f"extracted_facts_{ts}.jsonl"

    # Create empty files up-front so downstream steps can read them even if there are 0 rows.
    transcript_chunks_path.parent.mkdir(parents=True, exist_ok=True)
    transcript_chunks_path.touch(exist_ok=True)
    extracted_facts_path.touch(exist_ok=True)

    # Keep transcript chunks stable by chunk_index.
    transcript_chunk_rows.sort(key=lambda r: int(r.get("chunk_index") or 0))
    for r in transcript_chunk_rows:
        _write_jsonl(transcript_chunks_path, r)

    # Extracted facts already include created_at etc; keep stable by source_chunk_id then content.
    extracted_fact_rows.sort(
        key=lambda r: (
            str(r.get("source_chunk_id") or ""),
            str(r.get("fact_type") or ""),
            str(r.get("fact_content") or ""),
        )
    )
    for r in extracted_fact_rows:
        _write_jsonl(extracted_facts_path, r)

    facts_from_results = len(extracted_fact_rows)

    # Group + aggregate into inputs JSONL.
    print(f"meeting_id: {meeting_id}")
    print(f"chunks: {len(chunks)}")
    print(f"facts: {len(extracted_fact_rows)} (from_results={facts_from_results})")
    print(str(transcript_chunks_path))
    print(str(extracted_facts_path))

    # Group + aggregate into inputs JSONL (single-threaded by default to reduce rate-limit spikes).
    updated_facts_path: Path
    inputs_path: Path
    last_err: Exception | None = None
    for attempt in range(4):
        try:
            updated_facts_path, inputs_path = run_extracted_facts_to_inputs_jsonl(
                extracted_facts_path=extracted_facts_path,
                out_dir=out_dir,
                meeting_id=meeting_id,
                max_facts_per_call=int(args.max_facts_per_call),
                max_workers=1,
            )
            last_err = None
            break
        except Exception as e:
            last_err = e
            msg = str(e)
            if "rate_limit" in msg.lower() or "429" in msg:
                time.sleep(3)
                continue
            raise

    if last_err is not None:
        raise last_err

    print(str(updated_facts_path))
    print(str(inputs_path))

    # Also return a small stdout JSON summary for quick inspection.
    summary = {
        "meeting_id": meeting_id,
        "chunks": len(chunks),
        "facts": len(extracted_fact_rows),
        "artifacts": {
            "transcript_chunks": str(transcript_chunks_path),
            "extracted_facts": str(extracted_facts_path),
            "extracted_facts_labeled": str(updated_facts_path),
            "inputs": str(inputs_path),
        },
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
