from __future__ import annotations

import argparse
import json
import os
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from agents.aggregator_llm_node import aggregate_group_to_input
from agents.aggregator_router import route_facts_by_group_label
from agents.grouping_node import get_default_group_label, label_facts_with_group_labels


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


def run_extracted_facts_to_inputs_jsonl(
    *,
    extracted_facts_path: Path,
    out_dir: Path,
    meeting_id: str | None = None,
    max_facts_per_call: int = 30,
    max_workers: int = 4,
) -> tuple[Path, Path]:
    """Pipeline: extracted_facts (group_label null) -> grouping -> aggregation -> inputs JSONL.

    Returns (updated_extracted_facts_path, inputs_path)
    """

    rows = _read_jsonl(extracted_facts_path)
    if meeting_id is None:
        # Best-effort pick from first row
        meeting_id = rows[0].get("meeting_id") if rows else None

    # Only label rows without a group_label
    unlabeled = [r for r in rows if not r.get("group_label")]
    labeled = label_facts_with_group_labels(
        facts=unlabeled,
        meeting_id=meeting_id,
        max_facts_per_call=max_facts_per_call,
    )

    # Merge labeled back into original order by (fact_content, source_chunk_id, created_at) signature.
    # Since extracted_facts rows do not have ids yet, we match conservatively.
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

    # Aggregator Router: group facts by group_label
    groups = route_facts_by_group_label(merged_rows)

    if max_workers <= 0:
        max_workers = 1

    # Aggregate each group in parallel
    inputs_rows: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = [
            ex.submit(aggregate_group_to_input, meeting_id=meeting_id, group_label=gl, facts=facts)
            for gl, facts in groups.items()
        ]
        for fut in as_completed(futs):
            inputs_rows.append(fut.result())

    # Stable output order by group_label
    inputs_rows.sort(key=lambda r: str(r.get("group_label") or ""))

    out_dir.mkdir(parents=True, exist_ok=True)
    ts = int(time.time())
    updated_facts_path = out_dir / f"extracted_facts_labeled_{ts}.jsonl"
    inputs_path = out_dir / f"inputs_{ts}.jsonl"

    # Ensure outputs exist even when empty.
    updated_facts_path.touch(exist_ok=True)
    inputs_path.touch(exist_ok=True)

    for r in merged_rows:
        _write_jsonl(updated_facts_path, r)

    for r in inputs_rows:
        _write_jsonl(inputs_path, r)

    return updated_facts_path, inputs_path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Group extracted facts and aggregate into inputs JSONL.")
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
        help="How many facts to label per LLM call (default: GROUPING_MAX_FACTS_PER_CALL or 30)",
    )
    p.add_argument(
        "--max-workers",
        type=int,
        default=int(os.environ.get("AGG_MAX_WORKERS", "4")),
        help="Parallel aggregation workers (default: AGG_MAX_WORKERS or 4)",
    )

    args = p.parse_args(argv)

    updated_facts_path, inputs_path = run_extracted_facts_to_inputs_jsonl(
        extracted_facts_path=Path(args.extracted_facts),
        out_dir=Path(args.out_dir),
        meeting_id=args.meeting_id,
        max_facts_per_call=args.max_facts_per_call,
        max_workers=args.max_workers,
    )

    print(str(updated_facts_path))
    print(str(inputs_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
