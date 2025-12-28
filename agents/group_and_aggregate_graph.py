from __future__ import annotations

import argparse
import json
import operator
import os
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

from agents.aggregator_llm_node import aggregate_group_to_input
from agents.aggregator_router import route_facts_by_group_label
from agents.grouping_node import get_default_group_label, label_facts_with_group_labels


class GraphState(TypedDict, total=False):
    meeting_id: str | None
    extracted_facts_path: str
    out_dir: str
    max_facts_per_call: int
    max_workers: int

    # derived
    rows: list[dict[str, Any]]
    merged_rows: list[dict[str, Any]]
    groups: dict[str, list[dict[str, Any]]]

    # fan-in
    inputs_rows: Annotated[list[dict[str, Any]], operator.add]

    updated_facts_path: str
    inputs_path: str


def _state_dir() -> Path:
    return Path(os.environ.get("SMARTMEETOS_STATE_DIR", ".smartmeetos_state")).resolve()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    # Windows-safe: tolerate UTF-8 BOM (common in JSONL files produced by some tools)
    # by using utf-8-sig.
    text = path.read_text(encoding="utf-8-sig")
    for idx, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON on line {idx} of {path}: {e}") from e
    return rows


def _write_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def node_read(state: GraphState) -> GraphState:
    rows = _read_jsonl(Path(state["extracted_facts_path"]))
    meeting_id = state.get("meeting_id")
    if meeting_id is None:
        meeting_id = rows[0].get("meeting_id") if rows else None
    return {"rows": rows, "meeting_id": meeting_id}


def node_group_label(state: GraphState) -> GraphState:
    rows = state.get("rows", [])
    meeting_id = state.get("meeting_id")
    max_facts_per_call = int(state.get("max_facts_per_call", 30))

    unlabeled = [r for r in rows if not r.get("group_label")]
    labeled = label_facts_with_group_labels(
        facts=unlabeled,
        meeting_id=meeting_id,
        max_facts_per_call=max_facts_per_call,
    )

    def sig(r: dict[str, Any]) -> tuple[str, str, str]:
        return (
            str(r.get("fact_content") or ""),
            str(r.get("source_chunk_id") or ""),
            str(r.get("created_at") or ""),
        )

    # Duplicate-safe: multiple facts can share the same signature.
    labeled_by_sig: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in labeled:
        labeled_by_sig[sig(r)].append(r)

    merged_rows: list[dict[str, Any]] = []
    for r in rows:
        if r.get("group_label"):
            merged_rows.append(r)
            continue
        bucket = labeled_by_sig.get(sig(r))
        if bucket:
            merged_rows.append(bucket.pop(0))
        else:
            r2 = dict(r)
            r2["group_label"] = get_default_group_label()
            merged_rows.append(r2)

    return {"merged_rows": merged_rows}


def node_router(state: GraphState) -> GraphState:
    merged_rows = state.get("merged_rows", [])
    return {"groups": route_facts_by_group_label(merged_rows)}


def node_aggregate_parallel(state: GraphState) -> GraphState:
    groups = state.get("groups", {})
    meeting_id = state.get("meeting_id")

    max_workers = int(state.get("max_workers", 4))
    if max_workers <= 0:
        max_workers = 1

    inputs_rows: list[dict[str, Any]] = []
    if not groups:
        return {"inputs_rows": inputs_rows}

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = [
            ex.submit(aggregate_group_to_input, meeting_id=meeting_id, group_label=gl, facts=facts)
            for gl, facts in groups.items()
        ]
        for fut in as_completed(futs):
            inputs_rows.append(fut.result())

    inputs_rows.sort(key=lambda r: str(r.get("group_label") or ""))
    return {"inputs_rows": inputs_rows}


def node_write(state: GraphState) -> GraphState:
    out_dir = Path(state["out_dir"]).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    ts = int(time.time())
    updated_facts_path = out_dir / f"extracted_facts_labeled_{ts}.jsonl"
    inputs_path = out_dir / f"inputs_{ts}.jsonl"

    for r in state.get("merged_rows", []):
        _write_jsonl(updated_facts_path, r)

    for r in state.get("inputs_rows", []):
        _write_jsonl(inputs_path, r)

    return {"updated_facts_path": str(updated_facts_path), "inputs_path": str(inputs_path)}


def build_graph() -> Any:
    g = StateGraph(GraphState)

    g.add_node("read", node_read)
    g.add_node("grouping", node_group_label)
    g.add_node("router", node_router)
    g.add_node("aggregate_parallel", node_aggregate_parallel)
    g.add_node("write", node_write)

    g.add_edge(START, "read")
    g.add_edge("read", "grouping")
    g.add_edge("grouping", "router")
    g.add_edge("router", "aggregate_parallel")
    g.add_edge("aggregate_parallel", "write")
    g.add_edge("write", END)

    return g.compile()


def run_extracted_facts_to_inputs_jsonl_graph(
    *,
    extracted_facts_path: Path,
    out_dir: Path,
    meeting_id: str | None = None,
    max_facts_per_call: int = 30,
    max_workers: int = 4,
) -> tuple[Path, Path]:
    graph = build_graph()
    final_state = graph.invoke(
        {
            "meeting_id": meeting_id,
            "extracted_facts_path": str(extracted_facts_path),
            "out_dir": str(out_dir),
            "max_facts_per_call": int(max_facts_per_call),
            "max_workers": int(max_workers),
            "inputs_rows": [],
        }
    )

    return Path(final_state["updated_facts_path"]), Path(final_state["inputs_path"])


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="LangGraph: group extracted facts and aggregate into inputs JSONL.")
    p.add_argument("--extracted-facts", required=True, help="Path to extracted_facts_*.jsonl")
    p.add_argument("--meeting-id", default=None, help="Optional meeting id override")
    p.add_argument(
        "--out-dir",
        default=str(_state_dir() / "db_jsonl"),
        help="Output directory (default: SMARTMEETOS_STATE_DIR/db_jsonl)",
    )
    p.add_argument(
        "--max-facts-per-call",
        type=int,
        default=int(os.environ.get("GROUPING_MAX_FACTS_PER_CALL", "30")),
        help="Facts per grouping LLM call (default: GROUPING_MAX_FACTS_PER_CALL or 30)",
    )
    p.add_argument(
        "--max-workers",
        type=int,
        default=int(os.environ.get("AGG_MAX_WORKERS", "4")),
        help="Parallel aggregation workers (default: AGG_MAX_WORKERS or 4)",
    )

    args = p.parse_args(argv)

    labeled_facts_path, inputs_path = run_extracted_facts_to_inputs_jsonl_graph(
        extracted_facts_path=Path(args.extracted_facts),
        out_dir=Path(args.out_dir),
        meeting_id=args.meeting_id,
        max_facts_per_call=args.max_facts_per_call,
        max_workers=args.max_workers,
    )

    print(str(labeled_facts_path))
    print(str(inputs_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
