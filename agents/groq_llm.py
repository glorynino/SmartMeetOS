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

    import json

    return json.loads(content)
