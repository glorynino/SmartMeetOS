from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from database.connection import SessionLocal
from database.models import ExtractedFact, FactType, Inputs, MeetingSource, TranscriptChunk


def _parse_uuid(value: str, *, field_name: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except Exception as e:
        raise ValueError(f"{field_name} must be a UUID string, got {value!r}") from e


def _parse_dt(value: str) -> datetime:
    s = str(value)
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


class InputRow(BaseModel):
    meeting_id: str = Field(..., description="UUID string of meetings.id")
    group_label: str = Field(..., description="Group label for this input")
    input_content: str = Field(..., description="Final aggregated content")


class InsertInputsArgs(BaseModel):
    rows: list[InputRow] = Field(..., description="Rows to insert into inputs table")


@tool(args_schema=InsertInputsArgs)
def insert_inputs(rows: list[InputRow]) -> dict[str, Any]:
    """Insert aggregated inputs into the database.

    Safety properties:
    - Only inserts into the `inputs` table.
    - Validates UUIDs and clamps group_label length.
    """

    if not rows:
        return {"inserted": 0, "ids": []}

    db = SessionLocal()
    try:
        created_ids: list[str] = []
        for r in rows:
            meeting_uuid = _parse_uuid(r.meeting_id, field_name="meeting_id")

            gl = (r.group_label or "").strip()
            if len(gl) > 100:
                gl = gl[:100]

            obj = Inputs(
                meeting_id=meeting_uuid,
                group_label=gl,
                input_content=r.input_content,
            )
            db.add(obj)
            db.flush()  # assign obj.id
            created_ids.append(str(obj.id))

        db.commit()
        return {"inserted": len(created_ids), "ids": created_ids}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


class TranscriptChunkRow(BaseModel):
    id: str = Field(..., description="UUID string (transcript_chunks.id)")
    meeting_id: str = Field(..., description="UUID string (meetings.id)")
    chunk_index: int
    date: str = Field(..., description="ISO datetime string")
    speaker: str | None = None
    chunk_content: str
    source: str = Field(..., description='Enum value string like "Google Meet"')


class InsertTranscriptChunksArgs(BaseModel):
    rows: list[TranscriptChunkRow]


@tool(args_schema=InsertTranscriptChunksArgs)
def insert_transcript_chunks(rows: list[TranscriptChunkRow]) -> dict[str, Any]:
    """Insert transcript chunks into the database.

    Safety properties:
    - Inserts only into `transcript_chunks`.
    - Validates UUIDs and MeetingSource enum.
    """

    if not rows:
        return {"inserted": 0}

    db = SessionLocal()
    try:
        for r in rows:
            chunk_id = _parse_uuid(r.id, field_name="id")
            meeting_uuid = _parse_uuid(r.meeting_id, field_name="meeting_id")
            source_enum = MeetingSource(str(r.source))

            obj = TranscriptChunk(
                id=chunk_id,
                meeting_id=meeting_uuid,
                chunk_index=int(r.chunk_index),
                date=_parse_dt(r.date),
                speaker=r.speaker,
                chunk_content=r.chunk_content,
                source=source_enum,
            )
            db.add(obj)

        db.commit()
        return {"inserted": len(rows)}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


class ExtractedFactRow(BaseModel):
    meeting_id: str = Field(..., description="UUID string (meetings.id)")
    source_chunk_id: str = Field(..., description="UUID string (transcript_chunks.id)")
    speaker: str | None = None
    fact_type: str = Field(..., description="FactType enum value, e.g. action/decision")
    fact_content: str
    certainty: int = 70
    group_label: str | None = None
    created_at: str = Field(..., description="ISO datetime string")


class InsertExtractedFactsArgs(BaseModel):
    rows: list[ExtractedFactRow]


@tool(args_schema=InsertExtractedFactsArgs)
def insert_extracted_facts(rows: list[ExtractedFactRow]) -> dict[str, Any]:
    """Insert extracted facts into the database.

    Safety properties:
    - Inserts only into `extracted_facts`.
    - Validates UUIDs and FactType enum.
    - Leaves group_label nullable (can be None).
    """

    if not rows:
        return {"inserted": 0}

    db = SessionLocal()
    try:
        for r in rows:
            meeting_uuid = _parse_uuid(r.meeting_id, field_name="meeting_id")
            source_chunk_uuid = _parse_uuid(r.source_chunk_id, field_name="source_chunk_id")
            fact_type_enum = FactType(str(r.fact_type))

            certainty = int(r.certainty)
            if certainty < 0:
                certainty = 0
            if certainty > 100:
                certainty = 100

            gl = r.group_label
            if gl is not None:
                gl = str(gl).strip()
                if not gl:
                    gl = None
                elif len(gl) > 100:
                    gl = gl[:100]

            obj = ExtractedFact(
                meeting_id=meeting_uuid,
                source_chunk_id=source_chunk_uuid,
                speaker=r.speaker,
                fact_type=fact_type_enum,
                fact_content=r.fact_content,
                certainty=certainty,
                group_label=gl,
                created_at=_parse_dt(r.created_at),
            )
            db.add(obj)

        db.commit()
        return {"inserted": len(rows)}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
