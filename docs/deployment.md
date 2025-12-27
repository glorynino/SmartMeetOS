# Deployment

SmartMeetOS is a **multi-user** application that:

1. Authenticates users via Google OAuth (web-based flow)
2. Stores refresh tokens in PostgreSQL
3. Runs a cron worker that checks all users' calendars and triggers Nylas Notetakers
4. Receives transcript webhooks from Nylas and saves them to the database

## Architecture on Render

| Service              | Type        | Purpose                                           |
| -------------------- | ----------- | ------------------------------------------------- |
| `smartmeetos-web`    | Web Service | Flask app for OAuth flow + Nylas webhooks         |
| `smartmeetos-worker` | Cron Job    | Checks calendars every 5 min, triggers Notetakers |

Both services connect to your **existing PostgreSQL database**.

---

## Prerequisites

1. **PostgreSQL Database** - Already deployed (Supabase, Render Postgres, etc.)
2. **Google Cloud OAuth Credentials** - Web application type
3. **Nylas API Key** - From your Nylas dashboard

---

## 1) Google Cloud Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create or select a project
3. Enable **Google Calendar API**
4. Go to **APIs & Services → Credentials**
5. Create **OAuth 2.0 Client ID** (type: **Web application**)
6. Add authorized redirect URI:
   ```
   https://your-app.onrender.com/oauth/callback
   ```
7. Copy the **Client ID** and **Client Secret**

---

## 2) Nylas Setup

1. Create a webhook in Nylas Dashboard:
   - URL: `https://your-app.onrender.com/webhook`
   - Triggers: `notetaker.media`, `notetaker.updated`
2. Copy the **Webhook Secret** for signature verification

---

## 3) Deploy to Render

### Option A: Use Blueprint (Recommended)

1. Push this repo to GitHub
2. In Render Dashboard: **New → Blueprint**
3. Select your repository
4. Render will create both services from `render.yaml`

### Option B: Manual Setup

**Web Service:**

- Build Command: `pip install -r requirements.txt`
- Start Command: `gunicorn webapp.server:app --bind 0.0.0.0:$PORT --workers 2`
- Health Check Path: `/health`

**Cron Job:**

- Build Command: `pip install -r requirements.txt`
- Start Command: `python worker.py`
- Schedule: `*/5 * * * *` (every 5 minutes)

---

## 4) Environment Variables

Set these in **both services** on Render:

| Variable               | Required      | Description                                                                |
| ---------------------- | ------------- | -------------------------------------------------------------------------- |
| `DATABASE_URL`         | ✅            | PostgreSQL connection string                                               |
| `GOOGLE_CLIENT_ID`     | ✅            | From Google Cloud Console                                                  |
| `GOOGLE_CLIENT_SECRET` | ✅            | From Google Cloud Console                                                  |
| `NYLAS_API_KEY`        | ✅            | Your Nylas API key                                                         |
| `APP_BASE_URL`         | ✅ (web only) | Your Render web service URL (e.g., `https://smartmeetos-web.onrender.com`) |
| `NYLAS_WEBHOOK_SECRET` | Optional      | For webhook signature verification                                         |
| `FLASK_SECRET_KEY`     | Optional      | Session encryption (auto-generated if not set)                             |

---

## 5) Initialize Database

Run the database migrations to create the new tables:

```bash
# Locally with your DATABASE_URL set:
python database/init_db.py
```

Or run via Render Shell in the web service.

---

## 6) User Onboarding Flow

1. User visits: `https://your-app.onrender.com/oauth/login`
2. User is redirected to Google consent screen
3. User grants calendar access
4. Callback saves refresh token to database
5. Worker cron job will now check this user's calendar every 5 minutes

---

## 7) API Endpoints

| Endpoint          | Method   | Description                            |
| ----------------- | -------- | -------------------------------------- |
| `/`               | GET      | Service info + Nylas challenge handler |
| `/health`         | GET      | Health check                           |
| `/oauth/login`    | GET      | Start Google OAuth flow                |
| `/oauth/callback` | GET      | OAuth callback (saves tokens)          |
| `/webhook`        | GET/POST | Nylas webhook handler                  |
| `/users`          | GET      | List registered users (admin)          |
| `/transcripts`    | GET      | List recent transcripts (admin)        |

---

## 8) How the Worker Operates

Every 5 minutes, the cron job:

1. Queries all active users with Google refresh tokens
2. For each user:
   - Refreshes their Google access token
   - Fetches calendar events starting in the next 10 minutes
   - For events with Google Meet links:
     - Creates a Nylas Notetaker to join the meeting
     - Records the meeting in the database
3. When Nylas finishes recording:
   - Sends webhook to `/webhook`
   - Transcript is saved to database

---

## 9) Handling Overlapping Meetings

The worker handles multiple users with overlapping meetings gracefully:

- Each user is processed independently
- Each meeting gets its own Notetaker instance
- The worker checks if a Notetaker already exists for an event before creating a new one
- Different users can have Notetakers join the same meeting simultaneously

---

## 10) Monitoring

Check worker logs in Render Dashboard to see:

- Which users are being processed
- Which meetings are being triggered
- Any errors with token refresh or Notetaker creation

Example log output:

```
[2025-12-27T10:00:00Z] SmartMeetOS Worker starting
[2025-12-27T10:00:00Z] Found 3 active users with Google auth
[2025-12-27T10:00:01Z] Processing user: user@example.com
[2025-12-27T10:00:02Z]   Found meeting: Team Standup starting at 2025-12-27T10:05:00Z
[2025-12-27T10:00:03Z]   Created notetaker abc123 for meeting: Team Standup
[2025-12-27T10:00:04Z] Worker complete: 1 meetings triggered, 0 errors
```

---

## Local Development

Run the Flask server locally:

```bash
# Set environment variables
export DATABASE_URL="postgresql://..."
export GOOGLE_CLIENT_ID="..."
export GOOGLE_CLIENT_SECRET="..."
export NYLAS_API_KEY="..."
export APP_BASE_URL="http://localhost:8080"

# Start server
python -m webapp.server
```

Run the worker manually:

```bash
python worker.py
```

---

## Legacy Single-User Mode

The original CLI-based single-user mode (`check_calendar.py`) is still available for local development or single-user deployments. See the README for usage.
