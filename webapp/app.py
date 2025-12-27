import streamlit as st
import sys
import os
from datetime import datetime

# Add the project root to the path to import your modules
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

# --- Page Config ---
st.set_page_config(page_title="SmartMeetOS Test", layout="wide")
st.title("SmartMeetOS")

# --- Test Database Connection ---
st.header("1. Database Connection Test")
try:
    from database.connection import SessionLocal
    from database.models import User

    if SessionLocal is None:
        raise RuntimeError("DATABASE_URL is not set")

    db = SessionLocal()
    user_count = db.query(User).count()
    db.close()

    st.success(f"✅ Connected to Supabase! Found {user_count} user(s) in the database.")

except Exception as e:
    st.error(f"❌ Database connection failed: {e}")
    st.info("Check your `.env` file and ensure `DATABASE_URL` is set to the **Session Mode** pooler from Supabase.")

# --- Test Environment Variables ---
st.header("2. Environment Variables")
env_vars_to_check = ["DATABASE_URL", "NYLAS_API_KEY"]
for var in env_vars_to_check:
    value = os.environ.get(var)
    if value:
        # Hide most of the value for security
        displayed_value = value[:15] + "..." + value[-10:] if len(value) > 25 else "***SET***"
        st.code(f"{var}: {displayed_value}")
    else:
        st.warning(f"{var}: Not set in environment")

st.header("3. Calendar Watcher (real)")

try:
    from services.runtime_watcher import get_watcher_status, start_watcher, stop_watcher

    # Render best practice: run the watcher as a separate Background Worker.
    # The Streamlit web process should not spawn long-running subprocesses.
    if os.environ.get("RENDER") or os.environ.get("RENDER_SERVICE_ID"):
        st.info(
            "On Render, deploy the watcher as a separate Background Worker (see render.yaml / docs/deployment.md)."
        )
        st.stop()

    status = get_watcher_status()
    if status.running:
        st.success(f"Watcher running (pid={status.pid})")
    else:
        st.info("Watcher is stopped")

    with st.form("watcher_form"):
        calendar_id = st.text_input("Calendar ID", value="primary")
        poll_seconds = st.number_input("Poll seconds", min_value=5, max_value=300, value=15, step=1)
        grant_id = st.text_input(
            "Nylas Grant ID (or set NYLAS_GRANT_ID env var)",
            value=os.environ.get("NYLAS_GRANT_ID", ""),
        )
        enable_nylas = st.checkbox("Enable Nylas Notetaker", value=True)

        c1, c2 = st.columns(2)
        with c1:
            start_clicked = st.form_submit_button("Start watcher")
        with c2:
            stop_clicked = st.form_submit_button("Stop watcher")

    if start_clicked:
        st2 = start_watcher(
            calendar_id=calendar_id.strip() or "primary",
            poll_seconds=int(poll_seconds),
            nylas_notetaker=bool(enable_nylas),
            grant_id=(grant_id.strip() or None),
        )
        st.success(f"Started watcher (pid={st2.pid})")
        st.rerun()

    if stop_clicked:
        stop_watcher()
        st.success("Stopped watcher")
        st.rerun()

except Exception as e:
    st.error(f"Watcher controls unavailable: {e}")

