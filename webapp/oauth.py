"""
Web-based Google OAuth flow for multi-user server deployment.

This module provides OAuth endpoints that work without run_local_server().
It uses access_type='offline' and prompt='consent' to ensure refresh tokens.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from sqlalchemy.orm import Session

from database.connection import SessionLocal
from database.models import User


# Google OAuth configuration from environment
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")

# Scopes required for calendar access
SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/userinfo.email",
    "openid",
]


def get_oauth_redirect_uri() -> str:
    """Get the OAuth redirect URI from environment or default."""
    base_url = os.environ.get("APP_BASE_URL", "http://localhost:8501")
    return f"{base_url}/oauth/callback"


def get_client_config() -> dict[str, Any]:
    """Build OAuth client config from environment variables."""
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise ValueError(
            "GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET must be set in environment."
        )
    
    redirect_uri = get_oauth_redirect_uri()
    
    return {
        "web": {
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect_uri],
        }
    }


def create_authorization_url(state: str | None = None) -> tuple[str, str]:
    """
    Create the Google OAuth authorization URL.
    
    Returns:
        Tuple of (authorization_url, state)
    """
    client_config = get_client_config()
    redirect_uri = get_oauth_redirect_uri()
    
    flow = Flow.from_client_config(
        client_config,
        scopes=SCOPES,
        redirect_uri=redirect_uri,
    )
    
    authorization_url, state = flow.authorization_url(
        access_type="offline",
        prompt="consent",  # Force consent to always get refresh token
        include_granted_scopes="true",
        state=state,
    )
    
    return authorization_url, state


def exchange_code_for_tokens(authorization_code: str) -> dict[str, Any]:
    """
    Exchange the authorization code for access and refresh tokens.
    
    Returns:
        Dict with token info including refresh_token, access_token, email.
    """
    client_config = get_client_config()
    redirect_uri = get_oauth_redirect_uri()
    
    flow = Flow.from_client_config(
        client_config,
        scopes=SCOPES,
        redirect_uri=redirect_uri,
    )
    
    # Exchange code for tokens
    flow.fetch_token(code=authorization_code)
    credentials = flow.credentials
    
    if not credentials.refresh_token:
        raise ValueError(
            "No refresh token received. User may have already authorized this app. "
            "Revoke access at https://myaccount.google.com/permissions and try again."
        )
    
    # Get user email from ID token
    email = None
    if hasattr(credentials, "id_token") and credentials.id_token:
        # ID token contains user info
        import google.auth.transport.requests
        from google.oauth2 import id_token as id_token_module
        
        try:
            request = google.auth.transport.requests.Request()
            id_info = id_token_module.verify_oauth2_token(
                credentials.id_token, request, GOOGLE_CLIENT_ID
            )
            email = id_info.get("email")
        except Exception:
            pass
    
    # Fallback: fetch email from userinfo endpoint
    if not email:
        import requests
        
        headers = {"Authorization": f"Bearer {credentials.token}"}
        resp = requests.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers=headers,
            timeout=10,
        )
        if resp.status_code == 200:
            email = resp.json().get("email")
    
    return {
        "access_token": credentials.token,
        "refresh_token": credentials.refresh_token,
        "token_expiry": credentials.expiry,
        "email": email,
        "scopes": list(credentials.scopes) if credentials.scopes else SCOPES,
    }


def save_user_tokens(
    db: Session,
    email: str,
    google_email: str,
    refresh_token: str,
    token_expiry: datetime | None = None,
    nylas_grant_id: str | None = None,
) -> User:
    """
    Save or update user with Google OAuth tokens.
    
    Creates a new user if one doesn't exist with this email.
    """
    user = db.query(User).filter(User.email == email).first()
    
    if user:
        # Update existing user
        user.google_email = google_email
        user.google_refresh_token = refresh_token
        user.google_token_expiry = token_expiry
        if nylas_grant_id:
            user.nylas_grant_id = nylas_grant_id
        user.updated_at = datetime.now(timezone.utc)
    else:
        # Create new user
        user = User(
            email=email,
            google_email=google_email,
            google_refresh_token=refresh_token,
            google_token_expiry=token_expiry,
            nylas_grant_id=nylas_grant_id,
            is_active=True,
        )
        db.add(user)
    
    db.commit()
    db.refresh(user)
    return user


def get_credentials_from_refresh_token(refresh_token: str) -> Credentials:
    """
    Create Credentials object from a stored refresh token.
    
    This is used by the worker to authenticate on behalf of users.
    """
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise ValueError(
            "GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET must be set in environment."
        )
    
    credentials = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        scopes=SCOPES,
    )
    
    # Refresh to get a valid access token
    from google.auth.transport.requests import Request
    credentials.refresh(Request())
    
    return credentials


def revoke_user_tokens(refresh_token: str) -> bool:
    """Revoke a user's Google OAuth tokens."""
    import requests
    
    try:
        resp = requests.post(
            "https://oauth2.googleapis.com/revoke",
            params={"token": refresh_token},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=10,
        )
        return resp.status_code == 200
    except Exception:
        return False
