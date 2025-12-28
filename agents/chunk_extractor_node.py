from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any


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


class ChunkExtractorAgent:
    """LangChain-based agent for per-chunk fact extraction + DB writes.

    This agent uses Groq via OpenAI-compatible endpoint (through LangChain) and
    MUST write results by calling DB insertion tools.
    """

    def __init__(
        self,
        *,
        max_output_tokens: int | None = None,
    ) -> None:
        from agents.agent_factory import create_agent
        from agents.db_write_tools import insert_extracted_facts, insert_transcript_chunks
        from agents.groq_llm import groq_tool_model

        if max_output_tokens is None:
            max_output_tokens = int(os.environ.get("AGENT_MAX_OUTPUT_TOKENS", "900"))

        self._insert_transcript_chunks = insert_transcript_chunks
        self._insert_extracted_facts = insert_extracted_facts

        self._system_prompt = (
            "You are an agent that extracts facts from a meeting transcript chunk and writes them to a database. "
            "You MUST use the provided tools to write results. Return no free-form text."
        )

        self._agent = create_agent(
            model=groq_tool_model(max_tokens=int(max_output_tokens)),
            system_prompt=self._system_prompt,
            tools=[insert_transcript_chunks, insert_extracted_facts],
        )

    def run(
        self,
        chunk: Any,
        *,
        meeting_id: str,
        extractor_name: str = "default",
    ) -> dict[str, Any]:
        from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

        model = os.environ.get("GROQ_MODEL", "llama-3.1-8b-instant").strip()
        created_at = datetime.now(timezone.utc).isoformat()

        chunk_row: dict[str, Any] = {
            "id": str(getattr(chunk, "id")),
            "meeting_id": str(meeting_id),
            "chunk_index": int(getattr(chunk, "chunk_index")),
            "date": (
                getattr(chunk, "date").isoformat()
                if getattr(chunk, "date", None)
                else datetime.now(timezone.utc).isoformat()
            ),
            "speaker": getattr(chunk, "speaker", None),
            "chunk_content": str(getattr(chunk, "chunk_content")),
            "source": str(getattr(chunk, "source")),
        }

        system = self._system_prompt

        user = (
            "Task:\n"
            "1) Call insert_transcript_chunks with rows=[chunk_row] exactly as provided.\n"
            "2) Extract atomic facts from chunk_row.chunk_content and call insert_extracted_facts with rows=[...]\n"
            "\n"
            "Rules:\n"
            f"- meeting_id MUST be: {meeting_id}\n"
            f"- source_chunk_id MUST be: {chunk_row['id']}\n"
            f"- created_at for every fact MUST be: {created_at}\n"
            "- group_label MUST be null.\n"
            "- certainty MUST be an integer 0..100.\n"
            "- fact_type MUST be one of: "
            + ", ".join(FACT_TYPE_VALUES)
            + "\n"
            "- Do not invent facts. If nothing meaningful, call insert_extracted_facts with rows=[].\n"
            "\n"
            "chunk_row: "
            + json.dumps(chunk_row, ensure_ascii=False)
        )

        messages: list[Any] = [SystemMessage(content=system), HumanMessage(content=user)]

        saw_insert_chunk = False
        inserted_chunk_result: dict[str, Any] | None = None
        inserted_facts_result: dict[str, Any] | None = None
        inserted_fact_rows: list[dict[str, Any]] = []

        for _ in range(8):
            ai_msg = self._agent.llm.invoke(messages)
            messages.append(ai_msg)

            tool_calls = getattr(ai_msg, "tool_calls", None)
            if not tool_calls:
                raise RuntimeError(
                    "Extractor agent did not call tools (insert_transcript_chunks/insert_extracted_facts). "
                    "Check prompt/tool config."
                )

            for call in tool_calls:
                name = call.get("name")
                args = call.get("args") or {}
                call_id = call.get("id")

                if name == "insert_transcript_chunks":
                    inserted_chunk_result = self._insert_transcript_chunks.invoke(args)
                    saw_insert_chunk = True
                    messages.append(ToolMessage(content=json.dumps(inserted_chunk_result), tool_call_id=call_id))
                    continue

                if name == "insert_extracted_facts":
                    rows = args.get("rows") or []
                    if isinstance(rows, list):
                        inserted_fact_rows = [r for r in rows if isinstance(r, dict)]

                    inserted_facts_result = self._insert_extracted_facts.invoke(args)
                    messages.append(ToolMessage(content=json.dumps(inserted_facts_result), tool_call_id=call_id))
                    continue

                raise RuntimeError(f"Unexpected tool call: {name}")

            if saw_insert_chunk and inserted_facts_result is not None:
                break

        if inserted_facts_result is None:
            raise RuntimeError("Extractor agent did not complete insert_extracted_facts.")

        return {
            "meeting_id": meeting_id,
            "source_chunk_id": chunk_row["id"],
            "chunk_index": chunk_row["chunk_index"],
            "speaker": chunk_row.get("speaker"),
            "extractor": extractor_name,
            "model": model,
            "provider": "groq",
            "created_at": created_at,
            "facts": inserted_fact_rows,
            "db": {
                "insert_transcript_chunks": inserted_chunk_result,
                "insert_extracted_facts": inserted_facts_result,
            },
        }


def extract_facts_from_smart_chunk_via_langchain_tools(
    chunk: Any,
    *,
    meeting_id: str,
    extractor_name: str = "default",
) -> dict[str, Any]:
    """Extractor node where the LLM itself calls DB write tools.

    This uses LangChain tool-calling with Groq's OpenAI-compatible endpoint.

    Behavior:
    - The model MUST call:
      1) insert_transcript_chunks(rows=[...])
      2) insert_extracted_facts(rows=[...])

    Requires:
    - GROQ_API_KEY
    - DATABASE_URL
    - meeting_id is a UUID string matching meetings.id
    """

    agent = ChunkExtractorAgent()
    return agent.run(chunk, meeting_id=meeting_id, extractor_name=extractor_name)
