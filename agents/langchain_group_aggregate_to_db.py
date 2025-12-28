from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from agents.agent_factory import create_agent
from agents.db_write_tools import insert_inputs
from agents.groq_llm import groq_tool_model


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    text = path.read_text(encoding="utf-8-sig")
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def run_group_aggregate_and_write_inputs(
    *,
    extracted_facts_rows: list[dict[str, Any]],
    meeting_id: str,
) -> dict[str, Any]:
    """LangChain agent: group facts, aggregate, then call DB tool to insert inputs."""

    system = (
        "You are an agent that organizes meeting facts into groups and writes them into a database. "
        "You MUST use the provided tool to write results. Return no free-form text."
    )

    agent = create_agent(
        model=groq_tool_model(max_tokens=int(os.environ.get("AGENT_MAX_OUTPUT_TOKENS", "1200"))),
        system_prompt=system,
        tools=[insert_inputs],
    )

    compact_facts = [
        {
            "fact_type": r.get("fact_type"),
            "speaker": r.get("speaker"),
            "certainty": r.get("certainty"),
            "fact_content": r.get("fact_content"),
        }
        for r in extracted_facts_rows
    ]

    user = (
        "Task:\n"
        "1) Group the meeting facts into coherent categories (group_label <= 100 chars).\n"
        "2) For each group, produce a clean conflict-resolved summary called input_content.\n"
        "3) Call the tool insert_inputs with rows=[{meeting_id, group_label, input_content}, ...].\n\n"
        "Rules:\n"
        "- meeting_id MUST be the UUID string provided below.\n"
        "- group_label must be lowercase with underscores (examples: action_items, decisions, open_questions).\n"
        "- Do not invent facts. If a group has no content, omit it.\n\n"
        f"meeting_id: {meeting_id}\n"
        f"facts: {json.dumps(compact_facts, ensure_ascii=False)}"
    )

    messages: list[Any] = [SystemMessage(content=agent.system_prompt), HumanMessage(content=user)]

    # Simple tool-call loop
    for _ in range(6):
        ai_msg = agent.llm.invoke(messages)
        messages.append(ai_msg)

        tool_calls = getattr(ai_msg, "tool_calls", None)
        if not tool_calls:
            # If the model didn't call the tool, fail fast—this agent must write.
            raise RuntimeError("Agent did not call insert_inputs. Check prompt/tool config.")

        for call in tool_calls:
            name = call.get("name")
            args = call.get("args") or {}
            if name != "insert_inputs":
                raise RuntimeError(f"Unexpected tool call: {name}")

            result = insert_inputs.invoke(args)
            messages.append(ToolMessage(content=json.dumps(result), tool_call_id=call.get("id")))
            return result

    raise RuntimeError("Agent exceeded tool-call loop without completing.")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="LangChain agent: group+aggregate extracted facts and insert into DB.")
    p.add_argument("--extracted-facts", required=True, help="Path to extracted_facts_*.jsonl")
    p.add_argument("--meeting-id", required=True, help="Meeting UUID (meetings.id) to attach inputs")

    args = p.parse_args(argv)

    rows = _read_jsonl(Path(args.extracted_facts))
    result = run_group_aggregate_and_write_inputs(
        extracted_facts_rows=rows,
        meeting_id=args.meeting_id,
    )

    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
