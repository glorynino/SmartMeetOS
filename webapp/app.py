import asyncio
import json
import os
import subprocess
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel


import sys
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from database.connection import SessionLocal, engine
from database.models import Base, Meeting, ProcessingStatus, MeetingSource
from database import adapters
from database.models import User
from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

app = FastAPI(title="SmartMeetOS API", version="1.0.0")

NYLAS_API_KEY = os.getenv("NYLAS_API_KEY")
NYLAS_GRANT_ID = os.getenv("NYLAS_GRANT_ID")
BOT_POLL_INTERVAL = 15

class BotManager:
    def __init__(self):
        self.is_running = False
        self.process: Optional[subprocess.Popen] = None
        self.current_status = "stopped"
        self.last_activity = None
        self.active_meetings = []
        self._output_thread = None
        
    def _build_command(self) -> List[str]:
        return [
            "python", str(PROJECT_ROOT / "check_calendar.py"),
            "--calendar", "primary",
            "--poll-seconds", str(BOT_POLL_INTERVAL),
            "--nylas-notetaker",
            "--nylas-grant-id", NYLAS_GRANT_ID,
            "--nylas-api-key", NYLAS_API_KEY,
            "--nylas-notetaker-name", "SmartMeetOS Bot",
            "--client-secret", str(PROJECT_ROOT / "secret" / "client_secret.json"),
            "--nylas-max-denials", "1",
            "--nylas-max-kicks", "1",
        ]
    
    def start(self):
        if self.is_running:
            return
        
        try:
            cmd = self._build_command()
            print(f"Starting bot with command: {' '.join(cmd[:8])}...")
            
            self.process = subprocess.Popen(
                cmd,
                cwd=PROJECT_ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env={**os.environ, "PYTHONUNBUFFERED": "1"}
            )
            
            self.is_running = True
            self.current_status = "running"
            self.last_activity = datetime.now().isoformat()
            
            self._output_thread = threading.Thread(
                target=self._monitor_output,
                daemon=True
            )
            self._output_thread.start()
            
            print("Bot started successfully")
            
        except Exception as e:
            print(f"Failed to start bot: {e}")
            self.is_running = False
    
    def stop(self):
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
                print("Bot stopped gracefully")
            except:
                if self.process:
                    self.process.kill()
        
        self.is_running = False
        self.current_status = "stopped"
        self.active_meetings = []

    def _monitor_output(self):
        while self.is_running and self.process and self.process.stdout:
            line = self.process.stdout.readline()
            if line:
                clean_line = line.strip()
                print(f"[BOT] {clean_line}")

                if "TRANSCRIPT: saved" in clean_line:
                    if "saved " in clean_line:
                        transcript_path = clean_line.split("saved ", 1)[-1].strip()
                        process_transcript_file(transcript_path)

                self.last_activity = datetime.now().isoformat()


class PromptRequest(BaseModel):
    user_id: str
    prompt_text: str


# Global bot
bot_manager = BotManager()

def parse_transcript_json(transcript_path: Path) -> Optional[Dict]:
    try:
        with open(transcript_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        if data.get("object") == "transcript" and data.get("type") == "speaker_labelled":
            transcript_data = data.get("transcript", [])
            
            speaker_texts = {}
            for entry in transcript_data:
                speaker = entry.get("speaker", "Unknown")
                text = entry.get("text", "").strip()
                
                if speaker not in speaker_texts:
                    speaker_texts[speaker] = []
                
                speaker_texts[speaker].append(text)
            
            formatted_transcript = []
            for speaker, texts in speaker_texts.items():
                speaker_line = f"{speaker}: {' '.join(texts)}"
                formatted_transcript.append(speaker_line)
            
            return {
                "original_json": data,
                "speaker_texts": speaker_texts,
                "formatted_transcript": "\n".join(formatted_transcript),
                "total_speakers": len(speaker_texts),
                "total_entries": len(transcript_data)
            }
        
        return None
    except Exception as e:
        print(f"Error parsing transcript: {e}")
        return None


def extract_meeting_info_from_path(transcript_path: Path) -> Dict:
    filename = transcript_path.stem.replace('.transcript', '')
    parts = filename.split('__')
    
    start_time_str = parts[1] if len(parts) > 1 else None
    
    if start_time_str:
        if 'T' in start_time_str:
            date_part, time_zone_part = start_time_str.split('T')
            time_part, zone_part = time_zone_part.split('+')
            
            time_part = time_part.replace('-', ':')
            
            zone_part = zone_part.replace('-', ':')
            
            start_time_str = f"{date_part}T{time_part}+{zone_part}"
    
    info = {
        "event_id": parts[0] if len(parts) > 0 else None,
        "start_time": start_time_str,
        "notetaker_id": parts[2] if len(parts) > 2 else None,
        "filename": transcript_path.name
    }
    return info


def process_transcript_file(transcript_path_str: str):
    transcript_path = Path(transcript_path_str)
    
    if not transcript_path.exists():
        print(f"Transcript file not found: {transcript_path}")
        return
    
    print(f"Processing transcript: {transcript_path.name}")
    
    parsed_data = parse_transcript_json(transcript_path)
    if not parsed_data:
        print("Failed to parse transcript")
        return
    
    meeting_info = extract_meeting_info_from_path(transcript_path)
    
    db = SessionLocal()
    try:
        start_time = None
        if meeting_info["start_time"]:
            try:
                start_time = datetime.fromisoformat(meeting_info['start_time'])
            except ValueError as e:
                print(f"Could not parse date '{meeting_info['start_time']}': {e}")
                start_time = datetime.now()
        
        meeting = Meeting(
            id=uuid.uuid4(),
            title=f"Meeting {start_time.strftime('%Y-%m-%d %H:%M') if start_time else 'Unknown'}",
            start_time=start_time,
            end_time=datetime.now(),
            transcript_url=parsed_data["formatted_transcript"],
            status=ProcessingStatus.completed,
            source=MeetingSource.google_meet,
            created_at=datetime.now()
        )
        
        db.add(meeting)
        db.commit()
        db.refresh(meeting)
        
        print(f"✅ Saved transcript to database (Meeting ID: {meeting.id})")
        
        chunk_index = 0
        for speaker, texts in parsed_data["speaker_texts"].items():
            for text in texts:
                adapters.save_transcript_chunk(
                    meeting_id=meeting.id,
                    chunk_index=chunk_index,
                    speaker=speaker,
                    chunk_content=text,
                    source="Google Meet"
                )
                chunk_index += 1
        
        print(f"✅ Saved {chunk_index} transcript chunks")
        
    except Exception as e:
        db.rollback()
        print(f"❌ Database error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()



@app.on_event("startup")
async def startup_event():
    if NYLAS_API_KEY and NYLAS_GRANT_ID:
        print("🚀 Starting SmartMeetOS Bot...")
        bot_manager.start()
    else:
        print("⚠️ API keys not configured. Bot will not start.")

@app.on_event("shutdown")
async def shutdown_event():
    print("🛑 Stopping SmartMeetOS Bot...")
    bot_manager.stop()

@app.get("/")
async def root():
    return {
        "service": "SmartMeetOS Bot Server",
        "version": "1.0.0",
        "status": "running",
        "bot_status": bot_manager.current_status
    }

@app.get("/api/bot/status")
async def get_bot_status():
    return {
        "is_running": bot_manager.is_running,
        "status": bot_manager.current_status,
        "last_activity": bot_manager.last_activity,
        "active_meetings": bot_manager.active_meetings
    }

@app.post("/api/bot/start")
async def start_bot():
    if bot_manager.is_running:
        raise HTTPException(status_code=400, detail="Bot is already running")

    bot_manager.start()
    return {"message": "Bot started", "status": bot_manager.current_status}

@app.post("/api/bot/stop")
async def stop_bot():
    if not bot_manager.is_running:
        raise HTTPException(status_code=400, detail="Bot is not running")
    
    bot_manager.stop()
    return {"message": "Bot stopped", "status": bot_manager.current_status}

@app.get("/api/meetings")
async def get_meetings(limit: int = 10):
    db = SessionLocal()
    try:
        meetings = db.query(Meeting).order_by(Meeting.created_at.desc()).limit(limit).all()
        
        result = []
        for meeting in meetings:
            result.append({
                "id": str(meeting.id),
                "title": meeting.title,
                "start_time": meeting.start_time.isoformat() if meeting.start_time else None,
                "status": meeting.status.value if meeting.status else None,
                "source": meeting.source.value if meeting.source else None,
                "has_transcript": bool(meeting.transcript_url)
            })
        
        return {"meetings": result, "total": len(result)}
    finally:
        db.close()

@app.get("/api/meetings/{meeting_id}")
async def get_meeting(meeting_id: str):
    db = SessionLocal()
    try:
        meeting = db.query(Meeting).filter(Meeting.id == uuid.UUID(meeting_id)).first()
        
        if not meeting:
            raise HTTPException(status_code=404, detail="Meeting not found")
        
        chunks = adapters.get_transcript_chunks_for_meeting(meeting.id)
        
        return {
            "id": str(meeting.id),
            "title": meeting.title,
            "start_time": meeting.start_time.isoformat() if meeting.start_time else None,
            "end_time": meeting.end_time.isoformat() if meeting.end_time else None,
            "status": meeting.status.value if meeting.status else None,
            "source": meeting.source.value if meeting.source else None,
            "transcript": meeting.transcript_url,
            "chunks": [
                {
                    "speaker": chunk.speaker,
                    "content": chunk.chunk_content,
                    "index": chunk.chunk_index
                }
                for chunk in chunks
            ]
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid meeting ID")
    finally:
        db.close()

@app.post("/api/transcripts/process")
async def process_transcript(transcript_path: str):
    if not Path(transcript_path).exists():
        raise HTTPException(status_code=404, detail="Transcript file not found")

    from fastapi import BackgroundTasks
    background_tasks = BackgroundTasks()
    background_tasks.add_task(process_transcript_file, transcript_path)
    
    return {"message": "Transcript processing started"}

@app.get("/api/health")
async def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "bot_running": bot_manager.is_running,
        "database": "connected"
    }


@app.post("/api/users/{user_id}/prompt")
async def save_user_prompt(
    user_id: str,
    prompt_request: PromptRequest
):

    db = SessionLocal()
    try:
        user_uuid = uuid.UUID(user_id)

        user = db.query(User).filter(User.id == user_uuid).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        user.prompt = prompt_request.prompt_text

        db.commit()
        db.refresh(user)

        return {
            "message": "Prompt saved successfully",
            "user_id": str(user.id),
            "prompt": user.prompt[:100] + "..." if len(user.prompt) > 100 else user.prompt
        }

    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user ID format")
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    finally:
        db.close()



if __name__ == "__main__":
    Base.metadata.create_all(bind=engine)

    uvicorn.run(
        "webapp.app:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )