from __future__ import annotations

import argparse
import json
import os
import random
import threading
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


class _WindowRateLimiter:
    """Very small rate limiter for API usage.

    This is intentionally simple and conservative:
    - Enforces a per-minute request cap (RPM)
    - Enforces a per-minute token cap (TPM) using rough estimation

    It prevents accidental 429 storms when running chunk extraction in parallel.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._window_start = time.time()
        self._req_count = 0
        self._tok_count = 0

    def _reset_if_needed(self) -> None:
        now = time.time()
        if now - self._window_start >= 60.0:
            self._window_start = now
            self._req_count = 0
            self._tok_count = 0

    def acquire(self, *, est_tokens: int, rpm_limit: int, tpm_limit: int) -> None:
        while True:
            with self._lock:
                self._reset_if_needed()

                next_req = self._req_count + 1
                next_tok = self._tok_count + max(0, est_tokens)

                if next_req <= rpm_limit and next_tok <= tpm_limit:
                    self._req_count = next_req
                    self._tok_count = next_tok
                    return

                # Sleep until the next window.
                sleep_s = max(0.0, 60.0 - (time.time() - self._window_start))

            time.sleep(min(2.0, sleep_s) if sleep_s > 0 else 0.25)


_groq_limiter = _WindowRateLimiter()


def _estimate_tokens(text: str) -> int:
    # Rough heuristic: 1 token ~= 4 chars (English-ish). Good enough for throttling.
    return max(1, int(len(text) / 4))


def _groq_chat(
    *,
    model: str,
    messages: list[dict[str, Any]],
    api_key: str,
    timeout_s: float,
    max_output_tokens: int,
    rpm_limit: int,
    tpm_limit: int,
    max_attempts: int = 6,
) -> dict[str, Any]:
    url = "https://api.groq.com/openai/v1/chat/completions"

    # Token estimation for limiter (input + expected output).
    joined = "\n".join(str(m.get("content", "")) for m in messages)
    est = _estimate_tokens(joined) + max(32, max_output_tokens)
    _groq_limiter.acquire(est_tokens=est, rpm_limit=rpm_limit, tpm_limit=tpm_limit)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": max_output_tokens,
        # Ask for a JSON object response (OpenAI-style).
        "response_format": {"type": "json_object"},
    }

    last_err_text: str | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=timeout_s)
        except (requests.Timeout, requests.ConnectionError) as e:
            last_err_text = repr(e)
            resp = None

        if resp is None:
            # Exponential backoff with jitter.
            delay = min(10.0, 0.5 * (2 ** (attempt - 1))) + random.uniform(0.0, 0.25)
            time.sleep(delay)
            continue

        if resp.status_code == 200:
            return resp.json()

        if resp.status_code == 429:
            retry_after = resp.headers.get("retry-after") or resp.headers.get("Retry-After")
            if retry_after and retry_after.strip().isdigit():
                delay = float(retry_after.strip())
            else:
                delay = min(15.0, 0.75 * (2 ** (attempt - 1)))
                delay += random.uniform(0.0, 0.25)
            time.sleep(delay)
            continue

        if 500 <= resp.status_code <= 599:
            delay = min(10.0, 0.5 * (2 ** (attempt - 1))) + random.uniform(0.0, 0.25)
            time.sleep(delay)
            continue

        # Non-retriable: surface error.
        try:
            last_err_text = resp.text
        except Exception:
            last_err_text = f"HTTP {resp.status_code}"
        break

    raise RuntimeError(f"Groq chat failed after retries: {last_err_text}")


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

    # Default models:
    # - Ollama local dev: qwen2.5:7b-instruct
    # - Groq API (fast extraction at scale): llama-3.1-8b-instant
    if provider == "ollama":
        model = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b-instruct").strip()
        base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434").strip()
    elif provider == "groq":
        model = os.environ.get("GROQ_MODEL", "llama-3.1-8b-instant").strip()
        base_url = "https://api.groq.com"
    else:
        raise RuntimeError(
            "Unsupported LLM_PROVIDER. Use LLM_PROVIDER=ollama (local) or LLM_PROVIDER=groq (API)."
        )

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
    timeout_s = float(os.environ.get("LLM_TIMEOUT_SECONDS", "60"))
    max_output_tokens = int(os.environ.get("LLM_MAX_OUTPUT_TOKENS", "400"))

    if provider == "ollama":
        resp = _ollama_chat(model=model, messages=messages, base_url=base_url, timeout_s=timeout_s)
        content = (resp.get("message") or {}).get("content") if isinstance(resp, dict) else None
    else:
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            raise ValueError("Missing GROQ_API_KEY for LLM_PROVIDER=groq")

        # Conservative defaults for Groq Free plan to avoid 429s under parallel loads.
        rpm_limit = int(os.environ.get("GROQ_RPM_LIMIT", "25"))
        tpm_limit = int(os.environ.get("GROQ_TPM_LIMIT", "6000"))

        resp = _groq_chat(
            model=model,
            messages=messages,
            api_key=api_key,
            timeout_s=timeout_s,
            max_output_tokens=max_output_tokens,
            rpm_limit=rpm_limit,
            tpm_limit=tpm_limit,
        )

        # OpenAI-style response: choices[0].message.content
        try:
            content = resp["choices"][0]["message"]["content"]
        except Exception:
            content = None
    elapsed_ms = int((time.time() - started) * 1000)

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
