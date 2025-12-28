from __future__ import annotations

import os
from typing import Any

from langchain_openai import ChatOpenAI


def groq_chat_model(*, max_tokens: int, temperature: float = 0.2) -> ChatOpenAI:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError("Missing GROQ_API_KEY")

    base_url = os.environ.get("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
    model = os.environ.get("GROQ_MODEL", "llama-3.1-8b-instant")

    # Groq OpenAI-compatible endpoint (JSON response enforced)
    return ChatOpenAI(
        api_key=api_key,
        base_url=base_url,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        model_kwargs={"response_format": {"type": "json_object"}},
    )


def groq_tool_model(*, max_tokens: int, temperature: float = 0.2) -> ChatOpenAI:
    """Chat model configured for tool-calling.

    Important: we do NOT force response_format=json_object here because
    tool-calling responses are not JSON objects.
    """

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError("Missing GROQ_API_KEY")

    base_url = os.environ.get("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
    model = os.environ.get("GROQ_MODEL", "llama-3.1-8b-instant")

    return ChatOpenAI(
        api_key=api_key,
        base_url=base_url,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )


def groq_chat_json(*, messages: list[Any], max_tokens: int, temperature: float = 0.2) -> dict[str, Any]:
    """Invoke Groq chat model and parse JSON response.

    Requires the model to return valid JSON (we request json_object response_format).
    """

    llm = groq_chat_model(max_tokens=max_tokens, temperature=temperature)
    ai_msg = llm.invoke(messages)

    content = getattr(ai_msg, "content", None)
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("LLM returned empty content")

    if os.environ.get("SMARTMEETOS_DEBUG_GROQ_RAW"):
        try:
            from datetime import datetime, timezone
            from pathlib import Path

            state_dir = Path(os.environ.get("SMARTMEETOS_STATE_DIR", ".smartmeetos_state")).resolve()
            dbg_dir = state_dir / "debug"
            dbg_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            (dbg_dir / f"groq_raw_{ts}.txt").write_text(content, encoding="utf-8")
        except Exception:
            pass

    import json

    return json.loads(content)


def groq_chat_json_relaxed(*, messages: list[Any], max_tokens: int, temperature: float = 0.2) -> dict[str, Any]:
    """Invoke Groq chat model and best-effort parse JSON from text.

    Unlike `groq_chat_json`, this does NOT force `response_format=json_object`.
    This is useful when providers/models are strict or flaky with structured outputs.
    """

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError("Missing GROQ_API_KEY")

    base_url = os.environ.get("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
    model = os.environ.get("GROQ_MODEL", "llama-3.1-8b-instant")

    llm = ChatOpenAI(
        api_key=api_key,
        base_url=base_url,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    ai_msg = llm.invoke(messages)

    content = getattr(ai_msg, "content", None)
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("LLM returned empty content")

    if os.environ.get("SMARTMEETOS_DEBUG_GROQ_RAW"):
        try:
            from datetime import datetime, timezone
            from pathlib import Path

            state_dir = Path(os.environ.get("SMARTMEETOS_STATE_DIR", ".smartmeetos_state")).resolve()
            dbg_dir = state_dir / "debug"
            dbg_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            (dbg_dir / f"groq_raw_{ts}.txt").write_text(content, encoding="utf-8")
        except Exception:
            pass

    import json

    text = content.strip()

    # Strip common markdown fences.
    if text.startswith("```"):
        # Remove first fence line
        lines = text.splitlines()
        if lines:
            lines = lines[1:]
        # Drop trailing fence if present
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    # Some models wrap outputs like <function=name>{...}</function>
    if "<function" in text and "{" in text and "}" in text:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start : end + 1].strip()
    try:
        return json.loads(text)
    except Exception:
        # Best-effort: extract the first top-level JSON object.
        start = text.find("{")
        if start == -1:
            raise
        depth = 0
        end = -1
        for i in range(start, len(text)):
            ch = text[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end == -1:
            raise
        return json.loads(text[start : end + 1])
