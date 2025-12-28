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
        insert_transcript_chunks_tool: Any | None = None,
        insert_extracted_facts_tool: Any | None = None,
        write_transcript_chunks_via_tool: bool = True,
    ) -> None:
        from agents.agent_factory import create_agent
        from agents.groq_llm import groq_tool_model

        if max_output_tokens is None:
            max_output_tokens = int(os.environ.get("AGENT_MAX_OUTPUT_TOKENS", "900"))

        # Allow dependency injection for local tests (e.g., in-memory tools)
        # while keeping production behavior as DB-backed tools.
        if insert_transcript_chunks_tool is None or insert_extracted_facts_tool is None:
            # Import DB-backed tools lazily so local tests can run without DATABASE_URL.
            from agents.db_write_tools import insert_extracted_facts, insert_transcript_chunks

        self._insert_transcript_chunks = insert_transcript_chunks_tool or insert_transcript_chunks
        self._insert_extracted_facts = insert_extracted_facts_tool or insert_extracted_facts
        self._write_transcript_chunks_via_tool = bool(write_transcript_chunks_via_tool)

        self._system_prompt = (
            "You are an agent that extracts facts from a meeting transcript chunk and writes them to a database. "
            "You MUST use the provided tools to write results. Return no free-form text."
        )

        tools: list[Any]
        if self._write_transcript_chunks_via_tool:
            tools = [self._insert_transcript_chunks, self._insert_extracted_facts]
        else:
            tools = [self._insert_extracted_facts]

        self._agent = create_agent(
            model=groq_tool_model(max_tokens=int(max_output_tokens)),
            system_prompt=self._system_prompt,
            tools=tools,
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
                (
                    (getattr(chunk, "date").replace(tzinfo=timezone.utc) if getattr(chunk, "date").tzinfo is None else getattr(chunk, "date"))
                    .astimezone(timezone.utc)
                    .isoformat()
                )
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
            "- Extract at least: action items, decisions, questions, proposals, constraints, agreements/disagreements when present.\n"
            "- fact_type guidance: use action for commitments/tasks (e.g. 'I'll do X'); decision for explicit decisions; question for questions; proposal for suggestions; reminder for deadlines/time commitments; constraint for blockers/limits.\n"
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

        # For local tests (or strict tool validators), we can insert transcript chunks
        # directly in Python and let the model focus only on extracted facts.
        if not self._write_transcript_chunks_via_tool:
            inserted_chunk_result = self._insert_transcript_chunks.invoke({"rows": [chunk_row]})
            saw_insert_chunk = True
            messages = [
                SystemMessage(content=system),
                HumanMessage(
                    content=(
                        "Task:\n"
                        "1) Transcript chunk is already stored.\n"
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
                        "- Extract at least: action items, decisions, questions, proposals, constraints, agreements/disagreements when present.\n"
                        "- fact_type guidance: use action for commitments/tasks (e.g. 'I'll do X'); decision for explicit decisions; question for questions; proposal for suggestions; reminder for deadlines/time commitments; constraint for blockers/limits.\n"
                        "- Do not invent facts. If nothing meaningful, call insert_extracted_facts with rows=[].\n"
                        "\n"
                        "chunk_row: "
                        + json.dumps(chunk_row, ensure_ascii=False)
                    )
                ),
            ]

        def _fallback_extract_and_insert_facts() -> tuple[dict[str, Any], list[dict[str, Any]]]:
            """Fallback when provider/tool-calling fails.

            Uses JSON-only prompting (no tool calling) and then invokes the insertion tool in Python.
            """

            from langchain_core.messages import HumanMessage as _Human, SystemMessage as _System

            from agents.groq_llm import groq_chat_json, groq_chat_json_relaxed

            max_output_tokens = int(os.environ.get("EXTRACT_JSON_MAX_OUTPUT_TOKENS", "900"))
            max_facts = int(os.environ.get("EXTRACT_MAX_FACTS_PER_CHUNK", "10"))
            if max_facts <= 0:
                max_facts = 20
            if max_facts > 20:
                max_facts = 20

            schema_hint = {
                "facts": [
                    {
                        "speaker": None,
                        "fact_type": "statement",
                        "fact_content": "...",
                        "certainty": 70,
                    }
                ]
            }

            sys_prompt = (
                "You extract atomic meeting facts from a transcript chunk. "
                "Return ONLY valid JSON. Do not include explanations."
            )

            chunk_text = str(chunk_row.get("chunk_content") or "")

            # Prefer dialogue-like lines for extraction; many transcripts include prefaces.
            import re

            speaker_line_re = re.compile(r"^\s*[^:\n]{1,80}:\s+\S+", re.MULTILINE)
            dialogue_lines = [ln for ln in chunk_text.splitlines() if speaker_line_re.match(ln or "")]
            if dialogue_lines:
                chunk_text = "\n".join(dialogue_lines).strip()

            # Truncate to reduce output size and avoid provider truncation.
            # Keep the tail since it often contains the most recent/complete dialogue.
            max_chars = int(os.environ.get("EXTRACT_FALLBACK_MAX_CHARS", "2500"))
            if max_chars > 0 and len(chunk_text) > max_chars:
                chunk_text = chunk_text[-max_chars:]

            user_prompt = (
                "Extract atomic facts from this transcript chunk.\n"
                "Rules:\n"
                f"- meeting_id MUST be: {meeting_id}\n"
                f"- source_chunk_id MUST be: {chunk_row['id']}\n"
                f"- created_at for every fact MUST be: {created_at}\n"
                "- group_label MUST be null.\n"
                "- certainty MUST be an integer 0..100.\n"
                "- fact_type MUST be one of: "
                + ", ".join(FACT_TYPE_VALUES)
                + "\n"
                "- Extract at least: action items, decisions, questions, proposals, constraints, agreements/disagreements when present.\n"
                "- fact_type guidance: use action for commitments/tasks (e.g. 'I'll do X'); decision for explicit decisions; question for questions; proposal for suggestions; reminder for deadlines/time commitments; constraint for blockers/limits.\n"
                f"- Return at most {max_facts} facts.\n"
                "- Do not invent facts. If nothing meaningful, return facts=[].\n\n"
                "chunk_content:\n"
                + chunk_text
                + "\n\n"
                "Return JSON matching this shape: "
                + json.dumps(schema_hint, ensure_ascii=False)
            )

            try:
                # Prefer strict JSON mode when possible.
                data = groq_chat_json(
                    messages=[_System(content=sys_prompt), _Human(content=user_prompt)],
                    max_tokens=max_output_tokens,
                    temperature=0.0,
                )
            except Exception:
                try:
                    data = groq_chat_json_relaxed(
                        messages=[_System(content=sys_prompt), _Human(content=user_prompt)],
                        max_tokens=max_output_tokens,
                        temperature=0.2,
                    )
                except Exception:
                    # Retry with a stricter/shorter prompt.
                    tighter_max_facts = min(8, max_facts)
                    tighter_text = chunk_text[: min(len(chunk_text), 1200)]
                    retry_user = (
                        "Return ONLY a valid JSON object with a single key 'facts'.\n"
                        f"Return at most {tighter_max_facts} facts.\n"
                        "If you are unsure, return {\"facts\": []}.\n\n"
                        "fact_type MUST be one of: "
                        + ", ".join(FACT_TYPE_VALUES)
                        + "\n"
                        f"meeting_id: {meeting_id}\n"
                        f"source_chunk_id: {chunk_row['id']}\n"
                        f"created_at: {created_at}\n\n"
                        "chunk_content:\n"
                        + tighter_text
                    )
                    try:
                        data = groq_chat_json(
                            messages=[_System(content=sys_prompt), _Human(content=retry_user)],
                            max_tokens=max_output_tokens + 400,
                            temperature=0.0,
                        )
                    except Exception:
                        data = groq_chat_json_relaxed(
                            messages=[_System(content=sys_prompt), _Human(content=retry_user)],
                            max_tokens=max_output_tokens + 400,
                            temperature=0.0,
                        )

            facts = data.get("facts")
            if not isinstance(facts, list):
                facts = []

            if not facts and os.environ.get("SMARTMEETOS_DEBUG_FALLBACK"):
                try:
                    from pathlib import Path

                    state_dir = Path(os.environ.get("SMARTMEETOS_STATE_DIR", ".smartmeetos_state")).resolve()
                    dbg_dir = state_dir / "debug"
                    dbg_dir.mkdir(parents=True, exist_ok=True)
                    (dbg_dir / f"extract_fallback_{chunk_row['id']}.json").write_text(
                        json.dumps(
                            {
                                "meeting_id": meeting_id,
                                "source_chunk_id": chunk_row["id"],
                                "created_at": created_at,
                                "model": os.environ.get("GROQ_MODEL"),
                                "data": data,
                                "chunk_text_used": chunk_text,
                            },
                            ensure_ascii=False,
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
                except Exception:
                    pass

            cleaned: list[dict[str, Any]] = []
            allowed = set(FACT_TYPE_VALUES)
            for item in facts:
                if not isinstance(item, dict):
                    continue
                r = dict(item)
                r["meeting_id"] = str(meeting_id)
                r["source_chunk_id"] = str(chunk_row["id"])
                r["created_at"] = str(created_at)
                r["group_label"] = None

                ft = str(r.get("fact_type") or "").strip()
                if ft not in allowed:
                    ft = "statement"
                r["fact_type"] = ft

                fc = str(r.get("fact_content") or "").strip()
                if not fc:
                    continue
                r["fact_content"] = fc

                try:
                    c = int(r.get("certainty") if r.get("certainty") is not None else 70)
                except Exception:
                    c = 70
                if c < 0:
                    c = 0
                if c > 100:
                    c = 100
                r["certainty"] = c

                sp = r.get("speaker")
                if sp is not None:
                    sp = str(sp).strip()
                    r["speaker"] = sp if sp else None

                cleaned.append(r)

            result = self._insert_extracted_facts.invoke({"rows": cleaned})
            return result, cleaned

        for _ in range(8):
            try:
                ai_msg = self._agent.llm.invoke(messages)
            except Exception as e:
                # Some Groq models/providers are strict and may reject tool-calling attempts
                # with a 400 tool_use_failed even if the intent is correct.
                # Fall back to JSON-only extraction in that case.
                msg = str(e)
                if "tool_use_failed" in msg or "Failed to call a function" in msg:
                    inserted_facts_result, inserted_fact_rows = _fallback_extract_and_insert_facts()
                    break
                raise
            messages.append(ai_msg)

            tool_calls = getattr(ai_msg, "tool_calls", None)
            if not tool_calls:
                # If we get here without tool calls, fallback rather than hard-failing.
                inserted_facts_result, inserted_fact_rows = _fallback_extract_and_insert_facts()
                break

            for call in tool_calls:
                name = call.get("name")
                args = call.get("args") or {}
                call_id = call.get("id")

                if name == "insert_transcript_chunks":
                    # In normal mode the model is expected to call this.
                    # In local-test mode this tool isn't bound, but keep a guard anyway.
                    inserted_chunk_result = self._insert_transcript_chunks.invoke(args)
                    saw_insert_chunk = True
                    messages.append(ToolMessage(content=json.dumps(inserted_chunk_result), tool_call_id=call_id))
                    continue

                if name == "insert_extracted_facts":
                    rows = args.get("rows") or []
                    if isinstance(rows, list):
                        inserted_fact_rows = [r for r in rows if isinstance(r, dict)]

                    if os.environ.get("SMARTMEETOS_DEBUG_EXTRACTOR"):
                        try:
                            from pathlib import Path

                            state_dir = Path(os.environ.get("SMARTMEETOS_STATE_DIR", ".smartmeetos_state")).resolve()
                            dbg_dir = state_dir / "debug"
                            dbg_dir.mkdir(parents=True, exist_ok=True)
                            (dbg_dir / f"extract_toolcall_{chunk_row['id']}.json").write_text(
                                json.dumps(
                                    {
                                        "meeting_id": meeting_id,
                                        "source_chunk_id": chunk_row["id"],
                                        "created_at": created_at,
                                        "model": os.environ.get("GROQ_MODEL"),
                                        "rows_count": len(inserted_fact_rows),
                                        "rows": inserted_fact_rows,
                                    },
                                    ensure_ascii=False,
                                    indent=2,
                                ),
                                encoding="utf-8",
                            )
                        except Exception:
                            pass

                    inserted_facts_result = self._insert_extracted_facts.invoke(args)
                    messages.append(ToolMessage(content=json.dumps(inserted_facts_result), tool_call_id=call_id))
                    continue

                raise RuntimeError(f"Unexpected tool call: {name}")

            if inserted_facts_result is not None and (saw_insert_chunk or not self._write_transcript_chunks_via_tool):
                break

        if inserted_facts_result is None:
            # Last-resort fallback
            inserted_facts_result, inserted_fact_rows = _fallback_extract_and_insert_facts()

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
