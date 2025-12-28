from __future__ import annotations

# Renamed to match the architecture diagram:
# "Aggregator LLM Node (per group)"

import json
import os
from datetime import datetime, timezone
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from agents.groq_llm import groq_chat_json


def aggregate_group_to_input(
    *,
    meeting_id: str | None,
    group_label: str,
    facts: list[dict[str, Any]],
    model: str | None = None,
) -> dict[str, Any]:
    """Aggregator LLM Node.

    Input: facts belonging to the same group_label.
    Output: DB-shaped row for `inputs` table:
      - meeting_id
      - input_content
      - group_label
      - created_at

    This corresponds to the diagram: "Aggregator LLM Node for Group X".
    The same node code is invoked once per group.
    """

    max_output_tokens = int(os.environ.get("AGG_MAX_OUTPUT_TOKENS", "900"))

    items: list[dict[str, Any]] = []
    for f in facts:
        items.append(
            {
                "fact_type": f.get("fact_type"),
                "speaker": f.get("speaker"),
                "certainty": f.get("certainty"),
                "fact_content": f.get("fact_content"),
            }
        )

    system = (
        "You are a meeting synthesis system. "
        "Given extracted facts of a single theme/group, produce a clean, conflict-resolved summary. "
        "Return ONLY valid JSON."
    )

    schema_hint = {
        "input_content": "string (final resolved context for this group)",
    }

    user = (
        "Synthesize the following meeting facts into a single resolved input_content.\n"
        "Rules:\n"
        "- Remove duplicates and near-duplicates.\n"
        "- Resolve conflicts: if facts contradict, prefer the higher certainty or phrase uncertainty explicitly.\n"
        "- Keep it actionable and concise.\n"
        "- Use bullet points when it improves clarity.\n"
        "- Do not invent details not present in the facts.\n\n"
        f"meeting_id: {meeting_id}\n"
        f"group_label: {group_label}\n"
        f"facts: {json.dumps(items, ensure_ascii=False)}\n\n"
        f"Return JSON matching this shape: {json.dumps(schema_hint)}"
    )

    data = groq_chat_json(
        messages=[SystemMessage(content=system), HumanMessage(content=user)],
        max_tokens=max_output_tokens,
        temperature=0.2,
    )
    input_content = data.get("input_content")
    if not isinstance(input_content, str) or not input_content.strip():
        input_content = ""

    created_at = datetime.now(timezone.utc).isoformat()

    return {
        "meeting_id": meeting_id,
        "input_content": input_content.strip(),
        "group_label": group_label,
        "created_at": created_at,
    }
