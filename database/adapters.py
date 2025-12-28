import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

from database.connection import SessionLocal
from database.models import ServiceState, Meeting, TranscriptChunk


def save_trigger_state(event_id: str, start_utc_iso: str) -> bool:

    db: Session = SessionLocal()
    try:
        state = db.query(ServiceState).filter_by(service_name='calendar_triggers').first()
        if not state:
            state = ServiceState(service_name='calendar_triggers', state_json='{}')
            db.add(state)

        current_state = json.loads(state.state_json) if state.state_json else {}
        current_state[event_id] = start_utc_iso
        
        state.state_json = json.dumps(current_state)
        state.updated_at = datetime.now(timezone.utc)
        db.commit()
        return True
    except Exception as e:
        db.rollback()
        print(f"Error saving trigger state: {e}")
        return False
    finally:
        db.close()

def load_trigger_state() -> Dict[str, str]:

    db: Session = SessionLocal()
    try:
        state = db.query(ServiceState).filter_by(service_name='calendar_triggers').first()
        if state and state.state_json:
            return json.loads(state.state_json)
        return {}
    except Exception as e:
        print(f"Error loading trigger state: {e}")
        return {}
    finally:
        db.close()

def delete_trigger_state(event_id: str) -> bool:
    db: Session = SessionLocal()
    try:
        state = db.query(ServiceState).filter_by(service_name='calendar_triggers').first()
        if state and state.state_json:
            current_state = json.loads(state.state_json)
            if event_id in current_state:
                del current_state[event_id]
                state.state_json = json.dumps(current_state)
                state.updated_at = datetime.now(timezone.utc)
                db.commit()
                return True
        return False
    except Exception as e:
        db.rollback()
        print(f"Error deleting trigger state: {e}")
        return False
    finally:
        db.close()


def save_meeting_result(meeting_key: str, result_data: Dict[str, Any]) -> bool:

    db: Session = SessionLocal()
    try:
        state = db.query(ServiceState).filter_by(service_name='meeting_results').first()
        if not state:
            state = ServiceState(service_name='meeting_results', state_json='{}')
            db.add(state)
        
        current = json.loads(state.state_json) if state.state_json else {}
        current[meeting_key] = result_data
        
        state.state_json = json.dumps(current)
        state.updated_at = datetime.now(timezone.utc)
        db.commit()
        return True
    except Exception as e:
        db.rollback()
        print(f"Error saving meeting result: {e}")
        return False
    finally:
        db.close()

def load_meeting_results() -> Dict[str, Any]:

    db: Session = SessionLocal()
    try:
        state = db.query(ServiceState).filter_by(service_name='meeting_results').first()
        if state and state.state_json:
            return json.loads(state.state_json)
        return {}
    except Exception as e:
        print(f"Error loading meeting results: {e}")
        return {}
    finally:
        db.close()

def append_supervision_log(event_id: str, event_start_utc_iso: str, log_entry: Dict[str, Any]) -> bool:

    service_name = f"supervision_log_{event_id}_{event_start_utc_iso.replace(':', '-')}"
    db: Session = SessionLocal()
    try:
        state = db.query(ServiceState).filter_by(service_name=service_name).first()
        
        if not state:
            state = ServiceState(
                service_name=service_name,
                state_json='[]'
            )
            db.add(state)
            current_logs = []
        else:
            current_logs = json.loads(state.state_json) if state.state_json else []
        if 'ts_utc' not in log_entry:
            log_entry['ts_utc'] = datetime.now(timezone.utc).isoformat()
        
        current_logs.append(log_entry)

        state.state_json = json.dumps(current_logs)
        state.updated_at = datetime.now(timezone.utc)
        db.commit()
        return True
    except Exception as e:
        db.rollback()
        print(f"Error appending supervision log: {e}")
        return False
    finally:
        db.close()

def get_supervision_log(event_id: str, event_start_utc_iso: str) -> List[Dict[str, Any]]:

    service_name = f"supervision_log_{event_id}_{event_start_utc_iso.replace(':', '-')}"
    db: Session = SessionLocal()
    try:
        state = db.query(ServiceState).filter_by(service_name=service_name).first()
        if state and state.state_json:
            return json.loads(state.state_json)
        return []
    except Exception as e:
        print(f"Error getting supervision log: {e}")
        return []
    finally:
        db.close()


def acquire_active_lock(event_id: str, event_start_utc: str, expires_at_utc: str) -> bool:

    db: Session = SessionLocal()
    try:
        lock_state = db.query(ServiceState).filter_by(service_name='active_meeting_lock').first()
        if lock_state and lock_state.state_json:
            lock_data = json.loads(lock_state.state_json)
            lock_expires = datetime.fromisoformat(lock_data['expires_at_utc'].replace('Z', '+00:00'))
            if datetime.now(timezone.utc) < lock_expires:
                return False
        
        lock_data = {
            'event_id': event_id,
            'event_start_utc': event_start_utc,
            'expires_at_utc': expires_at_utc,
            'created_at_utc': datetime.now(timezone.utc).isoformat()
        }
        
        if not lock_state:
            lock_state = ServiceState(
                service_name='active_meeting_lock',
                state_json=json.dumps(lock_data)
            )
            db.add(lock_state)
        else:
            lock_state.state_json = json.dumps(lock_data)
        
        lock_state.updated_at = datetime.now(timezone.utc)
        db.commit()
        return True
        
    except Exception as e:
        db.rollback()
        print(f"Error acquiring active lock: {e}")
        return False
    finally:
        db.close()

def release_active_lock(event_id: str, event_start_utc: str) -> bool:

    db: Session = SessionLocal()
    try:
        lock_state = db.query(ServiceState).filter_by(service_name='active_meeting_lock').first()
        if lock_state and lock_state.state_json:
            lock_data = json.loads(lock_state.state_json)
            if lock_data.get('event_id') == event_id and lock_data.get('event_start_utc') == event_start_utc:
                lock_state.state_json = None
                lock_state.updated_at = datetime.now(timezone.utc)
                db.commit()
                return True
        return False
    except Exception as e:
        db.rollback()
        print(f"Error releasing active lock: {e}")
        return False
    finally:
        db.close()

def read_active_lock() -> Optional[Dict[str, str]]:

    db: Session = SessionLocal()
    try:
        lock_state = db.query(ServiceState).filter_by(service_name='active_meeting_lock').first()
        if lock_state and lock_state.state_json:
            return json.loads(lock_state.state_json)
        return None
    except Exception as e:
        print(f"Error reading active lock: {e}")
        return None
    finally:
        db.close()


def save_transcript_chunk(meeting_id: uuid.UUID, chunk_index: int, speaker: str, 
                          chunk_content: str, source: str) -> bool:

    db: Session = SessionLocal()
    try:
        chunk = TranscriptChunk(
            meeting_id=meeting_id,
            chunk_index=chunk_index,
            speaker=speaker,
            chunk_content=chunk_content,
            source=source
        )
        db.add(chunk)
        db.commit()
        return True
    except Exception as e:
        db.rollback()
        print(f"Error saving transcript chunk: {e}")
        return False
    finally:
        db.close()

def get_transcript_chunks_for_meeting(meeting_id: uuid.UUID) -> List[TranscriptChunk]:

    db: Session = SessionLocal()
    try:
        chunks = db.query(TranscriptChunk)\
            .filter_by(meeting_id=meeting_id)\
            .order_by(TranscriptChunk.chunk_index)\
            .all()
        return chunks
    except Exception as e:
        print(f"Error getting transcript chunks: {e}")
        return []
    finally:
        db.close()




def save_meeting_transcript(meeting_id: uuid.UUID, transcript_content: Any) -> bool:

    db: Session = SessionLocal()
    try:
        meeting = db.query(Meeting).filter_by(id=meeting_id).first()
        if meeting:
            if isinstance(transcript_content, (dict, list)):
                transcript_str = json.dumps(transcript_content, ensure_ascii=False)
            else:
                transcript_str = str(transcript_content)
            
            meeting.transcript_url = transcript_str
            meeting.updated_at = datetime.now(timezone.utc)
            db.commit()
            return True
        return False
    except Exception as e:
        db.rollback()
        print(f"Error saving meeting transcript: {e}")
        return False
    finally:
        db.close()

def get_meeting_transcript(meeting_id: uuid.UUID) -> Optional[Any]:

    db: Session = SessionLocal()
    try:
        meeting = db.query(Meeting).filter_by(id=meeting_id).first()
        if meeting and meeting.transcript_url:
            try:
                return json.loads(meeting.transcript_url)
            except json.JSONDecodeError:
                return meeting.transcript_url
        return None
    except Exception as e:
        print(f"Error getting meeting transcript: {e}")
        return None
    finally:
        db.close()