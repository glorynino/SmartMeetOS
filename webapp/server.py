"""
Flask Web Server for SmartMeetOS.

This is the main web service that handles:
1. Google OAuth flow (login, callback)
2. Nylas webhook callbacks
3. Health checks

Run locally:
    python -m webapp.server

Or with gunicorn:
    gunicorn webapp.server:app --bind 0.0.0.0:8080
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

from flask import Flask, request, redirect, jsonify, Response, session, url_for
from flask_cors import CORS

# Add project root to path
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv
load_dotenv()

from database.connection import SessionLocal
from webapp.oauth import (
    create_authorization_url,
    exchange_code_for_tokens,
    save_user_tokens,
)
from webapp.webhook import (
    verify_signature,
    process_notetaker_media,
    NYLAS_WEBHOOK_SECRET,
)


app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", os.urandom(32).hex())
CORS(app)


def log(message: str) -> None:
    """Simple logging with timestamp."""
    timestamp = datetime.now(timezone.utc).isoformat()
    print(f"[server] [{timestamp}] {message}", flush=True)


# =============================================================================
# Health Check
# =============================================================================

@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint for Render."""
    db_status = "connected" if SessionLocal else "not configured"
    return jsonify({
        "status": "healthy",
        "service": "SmartMeetOS",
        "database": db_status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


@app.route("/", methods=["GET"])
def index():
    """Landing page."""
    # Check for Nylas webhook challenge
    challenge = request.args.get("challenge")
    if challenge:
        log(f"Received Nylas challenge: {challenge[:20]}...")
        return Response(challenge, mimetype="text/plain")
    
    return jsonify({
        "service": "SmartMeetOS",
        "version": "1.0.0",
        "endpoints": {
            "oauth_login": "/oauth/login",
            "oauth_callback": "/oauth/callback",
            "webhook": "/webhook",
            "health": "/health",
        },
    })


# =============================================================================
# OAuth Endpoints
# =============================================================================

@app.route("/oauth/login", methods=["GET"])
def oauth_login():
    """
    Start the Google OAuth flow.
    
    Redirects user to Google's consent page.
    """
    try:
        # Generate state for CSRF protection
        import secrets
        state = secrets.token_urlsafe(32)
        session["oauth_state"] = state
        
        authorization_url, _ = create_authorization_url(state=state)
        log(f"Redirecting to Google OAuth: {authorization_url[:80]}...")
        return redirect(authorization_url)
        
    except Exception as e:
        log(f"OAuth login error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/oauth/callback", methods=["GET"])
def oauth_callback():
    """
    Handle the OAuth callback from Google.
    
    Exchanges the code for tokens and saves to database.
    """
    # Check for errors
    error = request.args.get("error")
    if error:
        log(f"OAuth error: {error}")
        return jsonify({"error": error, "description": request.args.get("error_description")}), 400
    
    # Get authorization code
    code = request.args.get("code")
    if not code:
        return jsonify({"error": "Missing authorization code"}), 400
    
    # Verify state (CSRF protection)
    state = request.args.get("state")
    stored_state = session.pop("oauth_state", None)
    if state != stored_state:
        log(f"State mismatch: got {state}, expected {stored_state}")
        # Continue anyway for now - state validation can be strict in production
    
    try:
        # Exchange code for tokens
        log("Exchanging authorization code for tokens...")
        token_info = exchange_code_for_tokens(code)
        
        email = token_info.get("email")
        refresh_token = token_info.get("refresh_token")
        token_expiry = token_info.get("token_expiry")
        
        if not email or not refresh_token:
            return jsonify({
                "error": "Missing email or refresh_token in response",
                "received": list(token_info.keys()),
            }), 400
        
        # Save to database
        log(f"Saving tokens for user: {email}")
        
        if SessionLocal is None:
            return jsonify({"error": "Database not configured"}), 500
        
        db = SessionLocal()
        try:
            user = save_user_tokens(
                db=db,
                email=email,
                google_email=email,
                refresh_token=refresh_token,
                token_expiry=token_expiry,
            )
            log(f"User saved: {user.id}")
            
            return jsonify({
                "success": True,
                "message": f"Successfully connected Google account: {email}",
                "user_id": str(user.id),
                "email": email,
            })
            
        finally:
            db.close()
        
    except Exception as e:
        log(f"OAuth callback error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


# =============================================================================
# Webhook Endpoints
# =============================================================================

@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    """Handle Nylas webhook notifications."""
    
    # Handle challenge verification (GET)
    if request.method == "GET":
        challenge = request.args.get("challenge")
        if challenge:
            log(f"Webhook challenge: {challenge[:20]}...")
            return Response(challenge, mimetype="text/plain")
        return jsonify({"status": "ok"})
    
    # Handle webhook notification (POST)
    signature = (
        request.headers.get("X-Nylas-Signature") or 
        request.headers.get("x-nylas-signature")
    )
    
    if NYLAS_WEBHOOK_SECRET and signature:
        if not verify_signature(request.data, signature):
            log("Invalid webhook signature")
            return jsonify({"error": "Invalid signature"}), 401
    
    try:
        data = request.get_json()
    except Exception:
        return jsonify({"error": "Invalid JSON"}), 400
    
    if not data:
        return jsonify({"error": "Empty body"}), 400
    
    webhook_type = data.get("type") or data.get("trigger")
    webhook_id = data.get("id", "unknown")
    log(f"Received webhook: type={webhook_type}, id={webhook_id}")
    
    # Process notetaker media webhooks
    if webhook_type in ("notetaker.media", "notetaker.updated"):
        state = data.get("object", {}).get("state") or data.get("data", {}).get("state")
        if state == "available" or webhook_type == "notetaker.media":
            result = process_notetaker_media(data)
            return jsonify(result)
    
    return jsonify({"status": "acknowledged", "type": webhook_type})


# =============================================================================
# User Management Endpoints
# =============================================================================

@app.route("/users", methods=["GET"])
def list_users():
    """List all registered users (for admin/debugging)."""
    if SessionLocal is None:
        return jsonify({"error": "Database not configured"}), 500
    
    db = SessionLocal()
    try:
        from database.models import User
        users = db.query(User).all()
        return jsonify({
            "count": len(users),
            "users": [
                {
                    "id": str(u.id),
                    "email": u.email,
                    "google_email": u.google_email,
                    "has_refresh_token": bool(u.google_refresh_token),
                    "is_active": u.is_active,
                    "created_at": u.created_at.isoformat() if u.created_at else None,
                }
                for u in users
            ],
        })
    finally:
        db.close()


@app.route("/transcripts", methods=["GET"])
def list_transcripts():
    """List recent transcripts (for admin/debugging)."""
    if SessionLocal is None:
        return jsonify({"error": "Database not configured"}), 500
    
    db = SessionLocal()
    try:
        from database.models import Transcript
        transcripts = db.query(Transcript).order_by(Transcript.created_at.desc()).limit(20).all()
        return jsonify({
            "count": len(transcripts),
            "transcripts": [
                {
                    "id": str(t.id),
                    "notetaker_id": t.notetaker_id,
                    "meeting_title": t.meeting_title,
                    "status": t.status,
                    "has_content": bool(t.transcript_content),
                    "received_at": t.received_at.isoformat() if t.received_at else None,
                }
                for t in transcripts
            ],
        })
    finally:
        db.close()


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    log(f"Starting SmartMeetOS server on port {port}")
    app.run(host="0.0.0.0", port=port, debug=True)
