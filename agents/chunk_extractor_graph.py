from __future__ import annotations

import argparse
import json
import operator
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

from agents.chunk_extractor_node import extract_facts_from_smart_chunk
from processing.smart_chunker_node import SmartChunk, smart_chunk_transcript


class GraphState(TypedDict, total=False):
    meeting_id: str | None
    source: str
    transcript_text: str
    max_chars: int
    overlap_chars: int

    # Derived
    chunks: list[SmartChunk]

    # Fan-in aggregation: each extractor returns a list with 1 record,
    # and LangGraph merges via operator.add
    extracted: Annotated[list[dict[str, Any]], operator.add]

    max_workers: int

    out_dir: str
    out_file: str
    chunks_out_file: str


def node_chunk(state: GraphState) -> GraphState:
    text = state.get("transcript_text", "")
    max_chars = int(state.get("max_chars", 2000))
    overlap_chars = int(state.get("overlap_chars", 200))
    meeting_id = state.get("meeting_id")
    source = str(state.get("source", "Google Meet"))

    chunks = smart_chunk_transcript(
        text,
        meeting_id=meeting_id,
        source=source,
        max_chars=max_chars,
        overlap_chars=overlap_chars,
    )
    return {"chunks": chunks}


def node_extract_parallel(state: GraphState) -> GraphState:
    chunks = state.get("chunks", [])
    meeting_id = state.get("meeting_id")

    # Bounded concurrency to avoid rate-limit storms.
    max_workers = int(state.get("max_workers", 4))
    if max_workers <= 0:
        max_workers = 1

    extracted: list[dict[str, Any]] = []
    if not chunks:
        return {"extracted": extracted}

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = [ex.submit(extract_facts_from_smart_chunk, c, meeting_id=meeting_id) for c in chunks]
        for fut in as_completed(futs):
            extracted.append(fut.result())

    # Keep output stable by chunk_index
    extracted.sort(key=lambda r: int(r.get("chunk_index") or 0))
    return {"extracted": extracted}


def node_write_jsonl(state: GraphState) -> GraphState:
    out_dir = Path(state["out_dir"]).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    out_file = out_dir / state["out_file"]
    chunks_out_file = out_dir / state["chunks_out_file"]

    def write_line(obj: dict[str, Any]) -> None:
        with out_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")

    for record in state.get("extracted", []):
        write_line(record)

    # Also write transcript_chunks rows (DB-shaped) so source_chunk_id FKs can be inserted.
    def write_chunk_line(obj: dict[str, Any]) -> None:
        with chunks_out_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")

    for c in sorted(state.get("chunks", []), key=lambda x: x.chunk_index):
        write_chunk_line(
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

    return {"out_file": str(out_file), "chunks_out_file": str(chunks_out_file)}


def build_graph() -> Any:
    g = StateGraph(GraphState)

    g.add_node("chunk", node_chunk)
    g.add_node("extract_parallel", node_extract_parallel)
    g.add_node("write", node_write_jsonl)

    g.add_edge(START, "chunk")

    g.add_edge("chunk", "extract_parallel")
    g.add_edge("extract_parallel", "write")
    g.add_edge("write", END)

    return g.compile()


def _default_state_dir() -> Path:
    return Path(os.environ.get("SMARTMEETOS_STATE_DIR", ".smartmeetos_state")).resolve()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="LangGraph pipeline: chunk -> parallel extract -> write JSONL.")
    p.add_argument("--input", required=True, help="Path to a UTF-8 transcript text file.")
    p.add_argument("--meeting-id", default=None, help="Optional meeting id.")
    p.add_argument(
        "--source",
        default="Google Meet",
        help='Meeting source label (DB enum value). Example: "Google Meet".',
    )
    p.add_argument("--max-chars", type=int, default=2000)
    p.add_argument("--overlap-chars", type=int, default=200)
    p.add_argument(
        "--out-dir",
        default=str(_default_state_dir() / "extracted_facts"),
        help="Output directory (default: SMARTMEETOS_STATE_DIR/extracted_facts).",
    )
    p.add_argument(
        "--max-workers",
        type=int,
        default=int(os.environ.get("EXTRACT_MAX_WORKERS", "4")),
        help="Max parallel chunk extraction workers (default: EXTRACT_MAX_WORKERS or 4).",
    )

    args = p.parse_args(argv)

    input_path = Path(args.input)
    transcript_text = input_path.read_text(encoding="utf-8")

    ts = int(time.time())
    out_file_name = f"extracted_facts_{input_path.stem}_{ts}.jsonl"
    chunks_out_file_name = f"transcript_chunks_{input_path.stem}_{ts}.jsonl"

    graph = build_graph()
    final_state = graph.invoke(
        {
            "meeting_id": args.meeting_id,
            "source": args.source,
            "transcript_text": transcript_text,
            "max_chars": args.max_chars,
            "overlap_chars": args.overlap_chars,
            "out_dir": str(Path(args.out_dir)),
            "out_file": out_file_name,
            "chunks_out_file": chunks_out_file_name,
            "extracted": [],
            "max_workers": args.max_workers,
            "run_at": datetime.now(timezone.utc).isoformat(),
        }
    )

    print(final_state["chunks_out_file"])
    print(final_state["out_file"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
