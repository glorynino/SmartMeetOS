from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from langchain_text_splitters import RecursiveCharacterTextSplitter


@dataclass(frozen=True)
class SmartChunk:
    """Output of the Smart Chunker Node.

    DB-aligned shape for `transcript_chunks` rows.
    """

    # transcript_chunks.id
    id: str
    # transcript_chunks.meeting_id
    meeting_id: str | None
    # transcript_chunks.chunk_index
    chunk_index: int
    # transcript_chunks.date
    date: datetime
    # transcript_chunks.speaker
    speaker: str | None
    # transcript_chunks.chunk_content
    chunk_content: str
    # transcript_chunks.source (MeetingSource enum value)
    source: str


def smart_chunk_transcript(
    transcript_text: str,
    *,
    meeting_id: str | None,
    source: str,
    max_chars: int = 2000,
    overlap_chars: int = 200,
) -> list[SmartChunk]:
    """Smart Chunker Node using a LangChain text splitter.

    This is deterministic (no LLM). We use a splitter to chunk text while
    prioritizing natural boundaries like paragraphs/newlines/sentences.
    """

    # Normalize dialog-like transcripts so chunk boundaries are more stable.
    # Expected rough input form:
    #   user1: text...
    #   user2: text...
    normalized = (transcript_text or "").replace("\r\n", "\n").strip()
    if not normalized:
        return []

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=max_chars,
        chunk_overlap=overlap_chars,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    pieces = splitter.split_text(normalized)

    speaker_re = re.compile(r"^\s*([^:\n]{1,80})\s*:\s+", re.MULTILINE)

    def infer_single_speaker(chunk_content: str) -> str | None:
        speakers = {m.group(1).strip() for m in speaker_re.finditer(chunk_content or "") if m.group(1).strip()}
        if len(speakers) == 1:
            return next(iter(speakers))
        return None

    out: list[SmartChunk] = []
    for i, text in enumerate(pieces, start=1):
        chunk_content = (text or "").strip()
        if not chunk_content:
            continue
        out.append(
            SmartChunk(
                id=str(uuid.uuid4()),
                meeting_id=meeting_id,
                chunk_index=i,
                date=datetime.now(timezone.utc),
                speaker=infer_single_speaker(chunk_content),
                chunk_content=chunk_content,
                source=source,
            )
        )

    return out
