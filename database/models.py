from sqlalchemy import Column, String, DateTime, Integer, Text, ForeignKey, Enum, JSON, Boolean
from sqlalchemy.dialects.postgresql import UUID
import enum
import uuid
from datetime import datetime
from .connection import Base

class MeetingSource(enum.Enum):
    google_meet = "Google Meet"
    zoom = "Zoom"
    microsoft_teams = "Microsoft Teams"

class ProcessingStatus(enum.Enum):
    pending = "pending"
    processing = "processing"
    completed = "completed"
    failed = "failed"

class FactType(enum.Enum):
    statement = "statement"
    proposal = "proposal"
    question = "question"
    decision = "decision"
    action = "action"
    constraint = "constraint"
    agreement = "agreement"
    disagreement = "disagreement"
    clarification = "clarification"
    condition = "condition"
    reminder = "reminder"

class DocumentType(enum.Enum):
    full_minutes = "full_minutes"
    workshop_notes = "workshop_notes"
    executive_summary = "executive_summary"
    personal_notes = "personal_notes"

class Urgency(enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"





class User(Base):
    __tablename__ = 'users'
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False)
    notion_token = Column(Text)
    notion_url = Column(Text)
    discord_id = Column(String(100))
    phone_number = Column(String(20))
    created_at = Column(DateTime, default=datetime.utcnow)

class Meeting(Base):
    __tablename__ = 'meetings'
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.id'))
    title = Column(String(500))
    start_time = Column(DateTime)
    end_time = Column(DateTime)
    transcript_url = Column(Text)
    status = Column(Enum(ProcessingStatus), default=ProcessingStatus.pending)
    source = Column(Enum(MeetingSource))
    created_at = Column(DateTime, default=datetime.utcnow)

class TranscriptChunk(Base):
    __tablename__ = 'transcript_chunks'
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    meeting_id = Column(UUID(as_uuid=True), ForeignKey('meetings.id'))
    chunk_index = Column(Integer, nullable=False)
    date = Column(DateTime, default=datetime.utcnow)
    speaker = Column(String(255))
    chunk_content = Column(Text, nullable=False)
    source = Column(Enum(MeetingSource))


class ExtractedFact(Base):
    __tablename__ = 'extracted_facts'
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    meeting_id = Column(UUID(as_uuid=True), ForeignKey('meetings.id'))
    source_chunk_id = Column(UUID(as_uuid=True), ForeignKey('transcript_chunks.id'), nullable=False)
    speaker = Column(String(255))
    fact_type = Column(Enum(FactType), nullable=False)
    fact_content = Column(Text, nullable=False)
    certainty = Column(Integer, default=70)
    group_label = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Inputs(Base):
    __tablename__ = 'inputs'
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    meeting_id = Column(UUID(as_uuid=True), ForeignKey('meetings.id'))
    input_content = Column(Text)
    group_label = Column(String(100))
    created_at = Column(DateTime, default=datetime.utcnow)

class DocumentOutput(Base):
    __tablename__ = 'document_outputs'
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    meeting_id = Column(UUID(as_uuid=True), ForeignKey('meetings.id'))
    agent = Column(String(100))
    document_type = Column(Enum(DocumentType), nullable=False)
    doc_content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class Task(Base):
    __tablename__ = 'tasks'
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    meeting_id = Column(UUID(as_uuid=True), ForeignKey('meetings.id'))
    task_title = Column(String(500), nullable=False)
    description = Column(Text)
    due_date = Column(DateTime)
    urgency = Column(Enum(Urgency), default=Urgency.medium)
    created_at = Column(DateTime, default=datetime.utcnow)

class CalendarEvent(Base):
    __tablename__ = 'calendar_events'
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    meeting_id = Column(UUID(as_uuid=True), ForeignKey('meetings.id'))
    event_type = Column(String(100))
    title = Column(String(500), nullable=False)
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=False)
    reminder_policy = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)