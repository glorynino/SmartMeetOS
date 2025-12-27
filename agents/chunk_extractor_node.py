from __future__ import annotations

import json
import os
import random
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import requests


@dataclass(frozen=True)
class ExtractedFact:
    fact_content: str
    source_quote: str
    certainty: int
    fact_type: str


# Keep in sync with database.models.FactType
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


class _WindowRateLimiter:
    """Small per-minute limiter to reduce 429 storms.

    Enforces both:
    - requests per minute (RPM)
    - tokens per minute (TPM) using rough estimation
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

                sleep_s = max(0.0, 60.0 - (time.time() - self._window_start))

            time.sleep(min(2.0, sleep_s) if sleep_s > 0 else 0.25)


_groq_limiter = _WindowRateLimiter()


def _estimate_tokens(text: str) -> int:
    # Rough heuristic: 1 token ~= 4 chars (English-ish). Good enough for throttling.
    return max(1, int(len(text) / 4))


def _extract_json_object(text: str) -> str:
    """Try to recover a JSON object from a messy model output."""

    s = (text or "").strip()
    if not s:
        return s

    if s.startswith("{") and s.endswith("}"):
        return s

    first = s.find("{")
    last = s.rfind("}")
    if first != -1 and last != -1 and last > first:
        return s[first : last + 1]

    return s


def _parse_facts_json(content: str) -> list[ExtractedFact]:
    """Parse model JSON content into ExtractedFact objects.

    Expected JSON shape:
            {
                "facts": [
                    {
                        "fact_type": "statement|proposal|question|decision|action|constraint|agreement|disagreement|clarification|condition|reminder",
                        "fact_content": "...",
                        "source_quote": "...",
                        "certainty": 0..100
                    }
                ]
            }
    """

    raw = _extract_json_object(content)
    data = json.loads(raw)

    facts_raw = data.get("facts", [])
    if not isinstance(facts_raw, list):
        return []

    facts: list[ExtractedFact] = []
    for item in facts_raw:
        if not isinstance(item, dict):
            continue

        fact_type = str(item.get("fact_type", "")).strip().lower()
        fact_content = str(item.get("fact_content", "")).strip()
        source_quote = str(item.get("source_quote", "")).strip()
        certainty_raw = item.get("certainty", 70)

        try:
            certainty_i = int(float(certainty_raw))
        except Exception:
            certainty_i = 70

        if not fact_content:
            continue

        if fact_type not in FACT_TYPE_VALUES:
            # If the model returns an unexpected value, keep the record but normalize to "statement".
            fact_type = "statement"

        certainty_i = max(0, min(100, certainty_i))

        facts.append(
            ExtractedFact(
                fact_content=fact_content,
                source_quote=source_quote,
                certainty=certainty_i,
                fact_type=fact_type,
            )
        )

    return facts


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

        try:
            last_err_text = resp.text
        except Exception:
            last_err_text = f"HTTP {resp.status_code}"
        break

    raise RuntimeError(f"Groq chat failed after retries: {last_err_text}")


def extract_facts_from_transcript_chunk(
    *,
    chunk_text: str,
    meeting_id: str | None = None,
    source_chunk_id: str | None = None,
    chunk_index: int | None = None,
    speaker: str | None = None,
    extractor_name: str = "default",
) -> dict[str, Any]:
    """Chunk Extractor LLM Node.

    Input: a single chunk of transcript text (already chunked elsewhere).
    Output: a JSON-serializable dict containing extracted facts.

    Required env vars:
    - GROQ_API_KEY

    Optional env vars:
    - GROQ_MODEL (default: llama-3.1-8b-instant)
    - GROQ_RPM_LIMIT (default: 25)
    - GROQ_TPM_LIMIT (default: 6000)
    - LLM_TIMEOUT_SECONDS (default: 60)
    - LLM_MAX_OUTPUT_TOKENS (default: 400)
    """

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError("Missing GROQ_API_KEY")

    model = os.environ.get("GROQ_MODEL", "llama-3.1-8b-instant").strip()
    timeout_s = float(os.environ.get("LLM_TIMEOUT_SECONDS", "60"))
    max_output_tokens = int(os.environ.get("LLM_MAX_OUTPUT_TOKENS", "400"))

    rpm_limit = int(os.environ.get("GROQ_RPM_LIMIT", "25"))
    tpm_limit = int(os.environ.get("GROQ_TPM_LIMIT", "6000"))

    system = (
        "You are a precise information extraction system. "
        "Extract actionable, atomic facts from meeting transcript text. "
        "Return ONLY valid JSON, no extra text."
    )

    schema_hint = {
        "facts": [
            {
                "fact_type": f"one of: {', '.join(FACT_TYPE_VALUES)}",
                "fact_content": "string (atomic fact)",
                "source_quote": "string (short exact quote from the chunk)",
                "certainty": "integer 0..100",
            }
        ]
    }

    user = (
        "Extract facts from the following transcript chunk.\n"
        "Rules:\n"
        "- Facts must be specific and independently true.\n"
        "- Prefer actions, decisions, constraints, questions, reminders.\n"
        "- fact_type MUST be one of the allowed enum values.\n"
        "- Use a short direct quote as evidence when possible.\n"
        "- certainty is an integer 0..100 (higher means more confident).\n"
        "- If nothing meaningful, return {\"facts\": []}.\n\n"
        f"Chunk:\n{chunk_text}\n\n"
        f"Return JSON matching this shape:\n{json.dumps(schema_hint)}"
    )

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

    started = time.time()
    resp = _groq_chat(
        model=model,
        messages=messages,
        api_key=api_key,
        timeout_s=timeout_s,
        max_output_tokens=max_output_tokens,
        rpm_limit=rpm_limit,
        tpm_limit=tpm_limit,
    )

    try:
        content = resp["choices"][0]["message"]["content"]
    except Exception:
        content = None

    elapsed_ms = int((time.time() - started) * 1000)

    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("LLM returned empty response content")

    facts = _parse_facts_json(content)

    created_at = datetime.now(timezone.utc).isoformat()

    return {
        "meeting_id": meeting_id,
        "source_chunk_id": source_chunk_id,
        "chunk_index": chunk_index,
        "speaker": speaker,
        "extractor": extractor_name,
        "model": model,
        "provider": "groq",
        "elapsed_ms": elapsed_ms,
        "created_at": created_at,
        "facts": [
            {
                "meeting_id": meeting_id,
                "source_chunk_id": source_chunk_id,
                "speaker": speaker,
                "fact_type": f.fact_type,
                "fact_content": f.fact_content,
                "certainty": f.certainty,
                "group_label": None,
                "created_at": created_at,
            }
            for f in facts
        ],
    }


def extract_facts_from_smart_chunk(
    chunk: Any,
    *,
    meeting_id: str | None = None,
    extractor_name: str = "default",
) -> dict[str, Any]:
    """Chunk Extractor LLM Node wrapper for SmartChunk.

    This lets the extractor node accept the output of
    `processing.smart_chunker_node.smart_chunk_transcript(...)` directly.
    """

    chunk_meeting_id = getattr(chunk, "meeting_id", None)
    return extract_facts_from_transcript_chunk(
        chunk_text=str(getattr(chunk, "chunk_content")),
        meeting_id=meeting_id if meeting_id is not None else chunk_meeting_id,
        source_chunk_id=str(getattr(chunk, "id")),
        chunk_index=int(getattr(chunk, "chunk_index")),
        speaker=getattr(chunk, "speaker", None),
        extractor_name=extractor_name,
    )
