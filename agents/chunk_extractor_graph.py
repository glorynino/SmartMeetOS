from __future__ import annotations

import argparse
import json
import operator
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

from agents.chunk_extractor import extract_facts_from_chunk
from processing.chunker import TextChunk, chunk_text


@dataclass(frozen=True)
class ChunkTask:
    chunk: TextChunk


class GraphState(TypedDict, total=False):
    meeting_id: str | None
    transcript_text: str
    max_chars: int
    overlap_chars: int

    # Derived
    chunks: list[TextChunk]

    # Fan-in aggregation: each extractor returns a list with 1 record,
    # and LangGraph merges via operator.add
    extracted: Annotated[list[dict[str, Any]], operator.add]

    out_dir: str
    out_file: str


def node_chunk(state: GraphState) -> GraphState:
    text = state.get("transcript_text", "")
    max_chars = int(state.get("max_chars", 2000))
    overlap_chars = int(state.get("overlap_chars", 200))

    chunks = chunk_text(text, max_chars=max_chars, overlap_chars=overlap_chars)
    return {"chunks": chunks}


def node_extract_one(state: GraphState) -> GraphState:
    # This node is invoked once per chunk via fan-out.
    chunk: TextChunk = state["chunk"]  # type: ignore[assignment]
    meeting_id = state.get("meeting_id")
    record = extract_facts_from_chunk(chunk, meeting_id=meeting_id)
    return {"extracted": [record]}


def node_write_jsonl(state: GraphState) -> GraphState:
    out_dir = Path(state["out_dir"]).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    out_file = out_dir / state["out_file"]

    def write_line(obj: dict[str, Any]) -> None:
        with out_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")

    for record in state.get("extracted", []):
        write_line(record)

    return {"out_file": str(out_file)}


def build_graph() -> Any:
    g = StateGraph(GraphState)

    g.add_node("chunk", node_chunk)
    g.add_node("extract_one", node_extract_one)
    g.add_node("write", node_write_jsonl)

    g.add_edge(START, "chunk")

    # Fan-out: route each chunk into its own extractor execution.
    def fan_out(state: GraphState):
        # Import locally to avoid requiring langgraph types at import time.
        from langgraph.types import Send

        sends = []
        for c in state.get("chunks", []):
            sends.append(Send("extract_one", {"chunk": c, "meeting_id": state.get("meeting_id")}))
        return sends

    g.add_conditional_edges("chunk", fan_out, ["extract_one"])

    # Fan-in: once all extract_one runs have contributed to `extracted`, continue.
    g.add_edge("extract_one", "write")
    g.add_edge("write", END)

    return g.compile()


def _default_state_dir() -> Path:
    return Path(os.environ.get("SMARTMEETOS_STATE_DIR", ".smartmeetos_state")).resolve()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="LangGraph pipeline: chunk -> parallel extract -> write JSONL.")
    p.add_argument("--input", required=True, help="Path to a UTF-8 transcript text file.")
    p.add_argument("--meeting-id", default=None, help="Optional meeting id.")
    p.add_argument("--max-chars", type=int, default=2000)
    p.add_argument("--overlap-chars", type=int, default=200)
    p.add_argument(
        "--out-dir",
        default=str(_default_state_dir() / "extracted_facts"),
        help="Output directory (default: SMARTMEETOS_STATE_DIR/extracted_facts).",
    )

    args = p.parse_args(argv)

    input_path = Path(args.input)
    transcript_text = input_path.read_text(encoding="utf-8")

    ts = int(time.time())
    out_file_name = f"extracted_facts_{input_path.stem}_{ts}.jsonl"

    graph = build_graph()
    final_state = graph.invoke(
        {
            "meeting_id": args.meeting_id,
            "transcript_text": transcript_text,
            "max_chars": args.max_chars,
            "overlap_chars": args.overlap_chars,
            "out_dir": str(Path(args.out_dir)),
            "out_file": out_file_name,
            "extracted": [],
            "run_at": datetime.now(timezone.utc).isoformat(),
        }
    )

    print(final_state["out_file"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
