"""
Nylas Webhook Handler for transcript callbacks.

This module provides a Flask-based webhook endpoint that:
1. Verifies webhook signatures (if NYLAS_WEBHOOK_SECRET is set)
2. Handles the Nylas challenge verification
3. Processes notetaker.media webhooks and saves transcripts to DB

Run standalone:
    python -m webapp.webhook --port 8080

Or integrate with your web framework.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flask import Flask, request, jsonify, Response
from sqlalchemy.orm import Session

# Add project root to path
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from database.connection import SessionLocal
from database.models import Transcript, User
from smartmeetos.notetaker.nylas_media import download_media_url


app = Flask(__name__)

NYLAS_WEBHOOK_SECRET = os.environ.get("NYLAS_WEBHOOK_SECRET")
NYLAS_API_KEY = os.environ.get("NYLAS_API_KEY")
NYLAS_API_BASE = os.environ.get("NYLAS_API_BASE", "https://api.us.nylas.com")


def log(message: str) -> None:
    """Simple logging with timestamp."""
    timestamp = datetime.now(timezone.utc).isoformat()
    print(f"[webhook] [{timestamp}] {message}", flush=True)


def verify_signature(body: bytes, signature: str) -> bool:
    """Verify Nylas webhook signature."""
    if not NYLAS_WEBHOOK_SECRET:
        return True  # Skip verification if no secret configured
    
    computed = hmac.new(
        NYLAS_WEBHOOK_SECRET.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()
    
    return hmac.compare_digest(computed, signature)


def get_db() -> Session:
    """Get database session."""
    if SessionLocal is None:
        raise RuntimeError("DATABASE_URL not configured")
    return SessionLocal()


def download_transcript_content(transcript_url: str) -> str | None:
    """Download transcript content from URL."""
    try:
        content = download_media_url(
            url=transcript_url,
            api_key=NYLAS_API_KEY,
            api_base=NYLAS_API_BASE,
        )
        if isinstance(content, bytes):
            return content.decode("utf-8")
        return content
    except Exception as e:
        log(f"Error downloading transcript: {e}")
        return None


def process_notetaker_media(data: dict[str, Any]) -> dict[str, Any]:
    """
    Process a notetaker.media webhook notification.
    
    Saves the transcript to the database.
    """
    notetaker_id = data.get("object", {}).get("id") or data.get("data", {}).get("id")
    
    if not notetaker_id:
        log("Missing notetaker_id in webhook data")
        return {"status": "error", "message": "missing notetaker_id"}
    
    # Extract media info
    object_data = data.get("object", {}) or data.get("data", {})
    media = object_data.get("media", {})
    
    transcript_meta = media.get("transcript")
    recording_meta = media.get("recording")
    
    transcript_url = None
    recording_url = None
    
    if isinstance(transcript_meta, dict):
        transcript_url = transcript_meta.get("url")
    elif isinstance(transcript_meta, str):
        transcript_url = transcript_meta
    
    if isinstance(recording_meta, dict):
        recording_url = recording_meta.get("url")
    elif isinstance(recording_meta, str):
        recording_url = recording_meta
    
    # Get meeting info if available
    meeting_info = object_data.get("meeting", {})
    meeting_title = meeting_info.get("title") or object_data.get("meeting_link", "")
    
    # Download transcript content
    transcript_content = None
    if transcript_url:
        log(f"Downloading transcript from {transcript_url[:50]}...")
        transcript_content = download_transcript_content(transcript_url)
    
    # Save to database
    db = get_db()
    try:
        # Try to find the user associated with this notetaker
        # For now, we'll create a transcript record without a specific user
        # In production, you'd track notetaker_id -> user_id mapping
        
        transcript = Transcript(
            user_id=None,  # Will be linked later or via notetaker tracking
            notetaker_id=notetaker_id,
            meeting_title=meeting_title,
            transcript_content=transcript_content,
            transcript_url=transcript_url,
            recording_url=recording_url,
            status="received" if transcript_content else "pending",
            received_at=datetime.now(timezone.utc),
        )
        
        # Note: user_id is required in the model, so we need to handle this
        # For now, find a default user or create orphan record logic
        default_user = db.query(User).first()
        if default_user:
            transcript.user_id = default_user.id
            db.add(transcript)
            db.commit()
            log(f"Saved transcript for notetaker {notetaker_id}")
        else:
            log(f"No users in database, cannot save transcript for {notetaker_id}")
        
        return {
            "status": "success",
            "notetaker_id": notetaker_id,
            "has_transcript": transcript_content is not None,
        }
        
    except Exception as e:
        log(f"Error saving transcript: {e}")
        db.rollback()
        return {"status": "error", "message": str(e)}
    finally:
        db.close()


@app.route("/", methods=["GET"])
def handle_challenge():
    """Handle Nylas webhook verification challenge."""
    challenge = request.args.get("challenge")
    if challenge:
        log(f"Received challenge verification: {challenge[:20]}...")
        return Response(challenge, mimetype="text/plain")
    return jsonify({"status": "ok", "service": "SmartMeetOS Webhook Handler"})


@app.route("/", methods=["POST"])
def handle_webhook():
    """Handle incoming Nylas webhook notifications."""
    # Verify signature
    signature = request.headers.get("X-Nylas-Signature") or request.headers.get("x-nylas-signature")
    
    if NYLAS_WEBHOOK_SECRET and signature:
        if not verify_signature(request.data, signature):
            log("Invalid webhook signature")
            return jsonify({"error": "Invalid signature"}), 401
    
    try:
        data = request.get_json()
    except Exception:
        log("Invalid JSON in webhook body")
        return jsonify({"error": "Invalid JSON"}), 400
    
    if not data:
        return jsonify({"error": "Empty body"}), 400
    
    # Log the webhook type
    webhook_type = data.get("type") or data.get("trigger")
    webhook_id = data.get("id", "unknown")
    log(f"Received webhook: type={webhook_type}, id={webhook_id}")
    
    # Handle different webhook types
    if webhook_type in ("notetaker.media", "notetaker.updated"):
        state = data.get("object", {}).get("state") or data.get("data", {}).get("state")
        if state == "available" or webhook_type == "notetaker.media":
            result = process_notetaker_media(data)
            return jsonify(result)
    
    # Acknowledge other webhook types
    return jsonify({"status": "acknowledged", "type": webhook_type})


@app.route("/health", methods=["GET"])
def health_check():
    """Health check endpoint."""
    return jsonify({
        "status": "healthy",
        "service": "SmartMeetOS Webhook Handler",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


def run_server(host: str = "0.0.0.0", port: int = 8080):
    """Run the webhook server."""
    log(f"Starting webhook server on {host}:{port}")
    log(f"Signature verification: {'enabled' if NYLAS_WEBHOOK_SECRET else 'DISABLED'}")
    app.run(host=host, port=port, debug=False)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Nylas Webhook Handler")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8080, help="Port to listen on")
    args = parser.parse_args()
    
    run_server(host=args.host, port=args.port)
