from __future__ import annotations

import json
import os
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from agents.groq_llm import groq_chat_json


_GROUP_LABEL_RE = re.compile(r"^[a-z0-9][a-z0-9_\-]{0,98}[a-z0-9]$|^[a-z0-9]$")


def get_default_group_label() -> str:
    # Configurable default for missing/unknown labels.
    # Example: set GROUPING_DEFAULT_LABEL=general
    value = os.environ.get("GROUPING_DEFAULT_LABEL", "ungrouped")
    return _normalize_group_label(value)


def _normalize_group_label(label: str) -> str:
    s = (label or "").strip().lower()
    s = re.sub(r"\s+", "_", s)
    s = re.sub(r"[^a-z0-9_\-]", "", s)
    s = s[:100]
    if not s:
        return os.environ.get("GROUPING_DEFAULT_LABEL", "ungrouped")
    if len(s) > 100:
        s = s[:100]
    # Ensure DB column constraint-ish (String(100)) and avoid weird empties.
    if not _GROUP_LABEL_RE.match(s):
        # Best-effort fallback normalization (still deterministic)
        s = re.sub(r"_+", "_", s).strip("_-")
        if not s:
            s = os.environ.get("GROUPING_DEFAULT_LABEL", "ungrouped")
        s = s[:100]
    return s


def label_facts_with_group_labels(
    *,
    facts: list[dict[str, Any]],
    meeting_id: str | None,
    max_facts_per_call: int = 30,
    model: str | None = None,
) -> list[dict[str, Any]]:
    """Grouping Node.

    Takes a list of DB-shaped extracted_facts rows and returns updated rows
    where each fact has a non-null `group_label`.

    This is intended to emulate the diagram step: "Queries ungrouped facts" -> "Labels facts with group_label".
    """

    # Grouping response is small.
    max_output_tokens = int(os.environ.get("GROUPING_MAX_OUTPUT_TOKENS", "600"))

    if max_facts_per_call <= 0:
        max_facts_per_call = 30

    updated: list[dict[str, Any]] = []

    def call_llm(batch: list[dict[str, Any]]) -> dict[str, str]:
        items = []
        for i, f in enumerate(batch):
            items.append(
                {
                    "i": i,
                    "fact_type": f.get("fact_type"),
                    "speaker": f.get("speaker"),
                    "fact_content": f.get("fact_content"),
                }
            )

        system = (
            "You are a semantic grouping system. "
            "Given extracted meeting facts, assign a concise group_label to each fact. "
            "Return ONLY valid JSON." 
        )

        schema_hint = {
            "labels": [
                {
                    "i": 0,
                    "group_label": "string (<=100 chars, lowercase, use underscores, e.g. action_items, decisions, open_questions)",
                }
            ]
        }

        user = (
            "Assign a group_label to each fact.\n"
            "Rules:\n"
            "- group_label MUST be <= 100 characters.\n"
            "- Use lowercase and underscores only.\n"
            "- Prefer stable labels like: action_items, decisions, open_questions, constraints, risks, next_steps, proposals, agreements, disagreements, reminders.\n"
            "- Facts that clearly belong together should share the same group_label.\n"
            "- If unsure, use group_label=\"ungrouped\".\n\n"
            f"meeting_id: {meeting_id}\n"
            f"facts: {json.dumps(items, ensure_ascii=False)}\n\n"
            f"Return JSON matching this shape: {json.dumps(schema_hint)}"
        )

        data = groq_chat_json(
            messages=[SystemMessage(content=system), HumanMessage(content=user)],
            max_tokens=max_output_tokens,
            temperature=0.2,
        )
        labels = data.get("labels")
        if not isinstance(labels, list):
            raise RuntimeError("Grouping LLM JSON must include 'labels' list")

        out: dict[str, str] = {}
        for item in labels:
            if not isinstance(item, dict):
                continue
            i = item.get("i")
            gl = item.get("group_label")
            if not isinstance(i, int):
                continue
            if not isinstance(gl, str):
                continue
            if 0 <= i < len(batch):
                out[str(i)] = _normalize_group_label(gl)

        # Ensure every fact has a label.
        for i in range(len(batch)):
            out.setdefault(str(i), get_default_group_label())

        return out

    for start in range(0, len(facts), max_facts_per_call):
        batch = facts[start : start + max_facts_per_call]
        labels_by_i = call_llm(batch)
        for i, f in enumerate(batch):
            f2 = dict(f)
            f2["group_label"] = _normalize_group_label(labels_by_i.get(str(i), get_default_group_label()))
            updated.append(f2)

    return updated
