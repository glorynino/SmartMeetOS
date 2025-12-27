from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from processing.chunker import TextChunk, chunk_text


@dataclass(frozen=True)
class ExtractedFact:
    fact: str
    source_quote: str
    confidence: float
    fact_type: str | None = None


def _state_dir() -> Path:
    # Simple local storage for now.
    # Can be overridden for deployments, tests, or different machines.
    return Path(os.environ.get("SMARTMEETOS_STATE_DIR", ".smartmeetos_state")).resolve()


def _ollama_chat(*, model: str, messages: list[dict[str, Any]], base_url: str, timeout_s: float = 60.0) -> dict[str, Any]:
    url = base_url.rstrip("/") + "/api/chat"
    payload = {
        "model": model,
        "messages": messages,
        # Ask Ollama to return strict JSON where supported.
        "format": "json",
        "stream": False,
        "options": {
            "temperature": 0.2,
        },
    }

    r = requests.post(url, json=payload, timeout=timeout_s)
    r.raise_for_status()
    return r.json()


def _parse_facts_json(content: str) -> list[ExtractedFact]:
    """Parse the model response content into ExtractedFact objects.

    Expected JSON shape:
      {"facts": [{"fact": "...", "source_quote": "...", "confidence": 0.0-1.0, "type": "..."}, ...]}
    """

    data = json.loads(content)
    facts_raw = data.get("facts", [])
    facts: list[ExtractedFact] = []

    if not isinstance(facts_raw, list):
        return facts

    for item in facts_raw:
        if not isinstance(item, dict):
            continue
        fact = str(item.get("fact", "")).strip()
        source_quote = str(item.get("source_quote", "")).strip()
        confidence = item.get("confidence", 0.0)
        fact_type = item.get("type")

        try:
            confidence_f = float(confidence)
        except Exception:
            confidence_f = 0.0

        if not fact:
            continue

        facts.append(
            ExtractedFact(
                fact=fact,
                source_quote=source_quote,
                confidence=max(0.0, min(1.0, confidence_f)),
                fact_type=str(fact_type).strip() if fact_type is not None else None,
            )
        )

    return facts


def extract_facts_from_chunk(chunk: TextChunk, *, meeting_id: str | None = None) -> dict[str, Any]:
    provider = os.environ.get("LLM_PROVIDER", "ollama").strip().lower()

    if provider != "ollama":
        raise RuntimeError(
            "Only LLM_PROVIDER=ollama is supported right now (free/local). "
            "Set LLM_PROVIDER=ollama and install/run Ollama."
        )

    model = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b-instruct").strip()
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434").strip()

    system = (
        "You are a precise information extraction system. "
        "Extract actionable, atomic facts from meeting transcript text. "
        "Return ONLY valid JSON, no extra text."
    )

    schema_hint = {
        "facts": [
            {
                "fact": "string (atomic fact)",
                "source_quote": "string (short exact quote from the chunk)",
                "confidence": "number 0..1",
                "type": "string | null (e.g. decision, action_item, risk, date, owner)"
            }
        ]
    }

    user = (
        "Extract facts from the following chunk.\n"
        "Rules:\n"
        "- Facts must be specific and independently true.\n"
        "- Prefer action items, decisions, dates, owners, risks.\n"
        "- Use a short direct quote as evidence when possible.\n"
        "- If nothing meaningful, return {\"facts\": []}.\n\n"
        f"Chunk:\n{chunk.text}\n\n"
        f"Return JSON matching this shape:\n{json.dumps(schema_hint)}"
    )

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

    started = time.time()
    resp = _ollama_chat(model=model, messages=messages, base_url=base_url)
    elapsed_ms = int((time.time() - started) * 1000)

    content = (
        (resp.get("message") or {}).get("content")
        if isinstance(resp, dict)
        else None
    )

    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("LLM returned empty response content")

    facts = _parse_facts_json(content)

    return {
        "meeting_id": meeting_id,
        "chunk_id": chunk.chunk_id,
        "model": model,
        "provider": provider,
        "elapsed_ms": elapsed_ms,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "facts": [
            {
                "fact": f.fact,
                "source_quote": f.source_quote,
                "confidence": f.confidence,
                "type": f.fact_type,
            }
            for f in facts
        ],
    }


def _write_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def run_file(*, input_path: Path, meeting_id: str | None, out_dir: Path, max_chars: int, overlap_chars: int) -> Path:
    text = input_path.read_text(encoding="utf-8")
    chunks = chunk_text(text, max_chars=max_chars, overlap_chars=overlap_chars)

    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"extracted_facts_{input_path.stem}_{int(time.time())}.jsonl"

    for chunk in chunks:
        record = extract_facts_from_chunk(chunk, meeting_id=meeting_id)
        _write_jsonl(out_file, record)

    return out_file


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Extract facts from transcript text using a free/local LLM (Ollama).")
    p.add_argument("--input", required=True, help="Path to a UTF-8 text file (transcript or chunked text).")
    p.add_argument("--meeting-id", default=None, help="Optional meeting id to include in output records.")
    p.add_argument("--max-chars", type=int, default=2000, help="Max chars per chunk.")
    p.add_argument("--overlap-chars", type=int, default=200, help="Overlap chars between chunks.")
    p.add_argument(
        "--out-dir",
        default=str(_state_dir() / "extracted_facts"),
        help="Output directory for JSONL records (default: SMARTMEETOS_STATE_DIR/extracted_facts).",
    )

    args = p.parse_args(argv)

    input_path = Path(args.input)
    out_dir = Path(args.out_dir)

    out_file = run_file(
        input_path=input_path,
        meeting_id=args.meeting_id,
        out_dir=out_dir,
        max_chars=args.max_chars,
        overlap_chars=args.overlap_chars,
    )

    print(str(out_file))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
