#!/usr/bin/env python3
"""
Worker script for Render Cron Job.

This script:
1. Queries the database for all active users with Google refresh tokens.
2. Uses their stored refresh_tokens to authenticate with Google.
3. Checks for meetings starting in the next 10 minutes.
4. Calls the Nylas Notetaker API to join the meeting.

Run via Render Cron Job every 5 minutes:
    python worker.py

Environment variables required:
    - DATABASE_URL
    - NYLAS_API_KEY
    - GOOGLE_CLIENT_ID
    - GOOGLE_CLIENT_SECRET
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any
from uuid import UUID

# Add project root to path
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy.orm import Session

from database.connection import SessionLocal
from database.models import User, Meeting, MeetingSource, ProcessingStatus
from webapp.oauth import get_credentials_from_refresh_token
from smartmeetos.calendar.google_calendar import GoogleCalendar
from smartmeetos.notetaker.nylas_notetaker import create_notetaker


# Configuration
LOOKAHEAD_MINUTES = 10  # Check for meetings starting in next N minutes
NYLAS_API_KEY = os.environ.get("NYLAS_API_KEY")
NYLAS_API_BASE = os.environ.get("NYLAS_API_BASE", "https://api.us.nylas.com")


def log(message: str) -> None:
    """Simple logging with timestamp."""
    timestamp = dt.datetime.now(dt.timezone.utc).isoformat()
    print(f"[{timestamp}] {message}", flush=True)


def get_active_users(db: Session) -> list[User]:
    """Get all active users with Google refresh tokens."""
    return (
        db.query(User)
        .filter(User.is_active == True)
        .filter(User.google_refresh_token.isnot(None))
        .all()
    )


def get_user_upcoming_meetings(
    user: User,
    lookahead_minutes: int = LOOKAHEAD_MINUTES,
) -> list[dict[str, Any]]:
    """
    Get upcoming meetings for a user from Google Calendar.
    
    Returns list of meetings starting within lookahead_minutes.
    """
    if not user.google_refresh_token:
        return []
    
    try:
        credentials = get_credentials_from_refresh_token(user.google_refresh_token)
        calendar = GoogleCalendar(credentials)
        
        now = dt.datetime.now(dt.timezone.utc)
        time_max = now + dt.timedelta(minutes=lookahead_minutes)
        
        events = calendar.list_upcoming_events(
            calendar_id="primary",
            time_min=now,
            time_max=time_max,
            max_results=10,
        )
        
        meetings = []
        for event in events:
            if event.meet_url:
                meetings.append({
                    "event_id": event.id,
                    "summary": event.summary,
                    "start": event.start,
                    "end": event.end,
                    "meet_url": event.meet_url,
                })
        
        return meetings
        
    except Exception as e:
        log(f"Error fetching calendar for user {user.email}: {e}")
        return []


def has_active_notetaker(db: Session, user_id: UUID, event_id: str) -> bool:
    """Check if we already have an active notetaker for this event."""
    existing = (
        db.query(Meeting)
        .filter(Meeting.user_id == user_id)
        .filter(Meeting.title.contains(event_id))
        .filter(Meeting.status.in_([ProcessingStatus.pending, ProcessingStatus.processing]))
        .first()
    )
    return existing is not None


def create_meeting_record(
    db: Session,
    user_id: UUID,
    event_id: str,
    title: str,
    start_time: dt.datetime,
    end_time: dt.datetime,
    notetaker_id: str,
) -> Meeting:
    """Create a meeting record in the database."""
    meeting = Meeting(
        user_id=user_id,
        title=f"{title} [{event_id}]",
        start_time=start_time,
        end_time=end_time,
        source=MeetingSource.google_meet,
        status=ProcessingStatus.processing,
    )
    db.add(meeting)
    db.commit()
    db.refresh(meeting)
    return meeting


def trigger_notetaker_for_meeting(
    user: User,
    meeting: dict[str, Any],
) -> str | None:
    """
    Create a Nylas Notetaker for the meeting.
    
    Returns the notetaker_id if successful, None otherwise.
    """
    if not NYLAS_API_KEY:
        log("NYLAS_API_KEY not set, skipping notetaker creation")
        return None
    
    meet_url = meeting["meet_url"]
    summary = meeting["summary"] or "Meeting"
    
    # Use user's nylas_grant_id if available, otherwise use standalone notetaker
    grant_id = user.nylas_grant_id or ""
    
    try:
        result = create_notetaker(
            meeting_link=meet_url,
            notetaker_name="SmartMeetOS Recorder",
            grant_id=grant_id,
            api_key=NYLAS_API_KEY,
            api_base=NYLAS_API_BASE,
        )
        
        notetaker_id = result.get("data", {}).get("id")
        if notetaker_id:
            log(f"Created notetaker {notetaker_id} for meeting: {summary}")
            return notetaker_id
        else:
            log(f"Notetaker creation response missing ID: {result}")
            return None
            
    except Exception as e:
        log(f"Error creating notetaker for {summary}: {e}")
        return None


def process_user(db: Session, user: User) -> int:
    """
    Process a single user: check meetings and trigger notetakers.
    
    Returns the number of meetings triggered.
    """
    log(f"Processing user: {user.email}")
    
    meetings = get_user_upcoming_meetings(user)
    
    if not meetings:
        log(f"  No upcoming meetings with Meet links for {user.email}")
        return 0
    
    triggered = 0
    for meeting in meetings:
        event_id = meeting["event_id"]
        summary = meeting["summary"] or "Untitled"
        
        # Skip if we already have an active notetaker for this event
        if has_active_notetaker(db, user.id, event_id):
            log(f"  Skipping {summary} - already has active notetaker")
            continue
        
        log(f"  Found meeting: {summary} starting at {meeting['start']}")
        
        # Trigger notetaker
        notetaker_id = trigger_notetaker_for_meeting(user, meeting)
        
        if notetaker_id:
            # Record in database
            create_meeting_record(
                db=db,
                user_id=user.id,
                event_id=event_id,
                title=summary,
                start_time=meeting["start"],
                end_time=meeting["end"],
                notetaker_id=notetaker_id,
            )
            triggered += 1
    
    return triggered


def run_worker() -> None:
    """Main worker loop."""
    log("=" * 60)
    log("SmartMeetOS Worker starting")
    log("=" * 60)
    
    if not NYLAS_API_KEY:
        log("WARNING: NYLAS_API_KEY not set - notetakers will not be created")
    
    if SessionLocal is None:
        log("ERROR: DATABASE_URL not configured")
        sys.exit(1)
    
    db = SessionLocal()
    
    try:
        users = get_active_users(db)
        log(f"Found {len(users)} active users with Google auth")
        
        total_triggered = 0
        errors = 0
        
        for user in users:
            try:
                triggered = process_user(db, user)
                total_triggered += triggered
            except Exception as e:
                log(f"Error processing user {user.email}: {e}")
                traceback.print_exc()
                errors += 1
        
        log("-" * 60)
        log(f"Worker complete: {total_triggered} meetings triggered, {errors} errors")
        log("=" * 60)
        
    finally:
        db.close()


if __name__ == "__main__":
    run_worker()
