import streamlit as st
import sys
import os
from datetime import datetime

# Add the project root to the path to import your modules
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

# --- Page Config ---
st.set_page_config(page_title="SmartMeetOS Test", layout="wide")
st.title("🔧 SmartMeetOS - Local Connection Test")

# --- Test Database Connection ---
st.header("1. Database Connection Test")
try:
    from database.connection import SessionLocal
    from database.models import User
    
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

# --- Mock Agent Test ---
st.header("3. Mock Agent Pipeline")
if st.button("Simulate Meeting Processing"):
    with st.spinner("Simulating pipeline..."):
        # Simulate your processing steps
        steps = [
            "Chunking transcript...",
            "Extracting facts...",
            "Grouping facts...",
            "Resolving conflicts...",
            "Creating Notion summary...",
            "Sending Discord notification..."
        ]

        progress_bar = st.progress(0)
        status_text = st.empty()

        for i, step in enumerate(steps):
            status_text.text(f"Step {i+1}/6: {step}")
            progress_bar.progress((i + 1) / 6)
            import time
            time.sleep(0.5)  # Simulate work

        st.success("✅ Pipeline simulation complete!")
        st.balloons()

