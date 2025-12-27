# Google Calendar checker (Step 1)

This is the first building block for SmartMeetOS: read upcoming meetings from Google Calendar and extract Google Meet URLs.

## Security

- Your OAuth client JSON contains a **client secret**. Treat it like a password.
- Do not commit it. This repo's `.gitignore` ignores `secrets/` and `.secrets/`.
- If your secret was exposed publicly, rotate/recreate the OAuth credential in Google Cloud.

## 1) Google Cloud setup

1. Open Google Cloud Console and select your project.
2. Enable **Google Calendar API**.
3. Configure the **OAuth consent screen** and add yourself as a test user if required.
4. Create OAuth credentials:
   - Recommended: create a **Desktop app** OAuth client.
   - If you keep a **Web application** client, add an Authorized redirect URI: `http://localhost:8080/`.
5. Download the OAuth client JSON.

## 2) Place credentials locally

Option A (recommended for this repo):

- Put your downloaded JSON at: `secrets/client_secret.json`

Option B:

- Set `GOOGLE_CLIENT_SECRET_FILE` to the JSON path anywhere on disk.

The script stores the user token at: `.secrets/google_token.json` (also ignored by git).

## 3) Install dependencies

From repo root:

- `C:/Users/Abderrahmane/Desktop/SmartMeetOS/.venv/Scripts/python.exe -m pip install -r requirements.txt`

## 4) Run

One-time check (looks ahead 2 hours):

- `C:/Users/Abderrahmane/Desktop/SmartMeetOS/.venv/Scripts/python.exe check_calendar.py`

Poll every 60 seconds:

- `C:/Users/Abderrahmane/Desktop/SmartMeetOS/.venv/Scripts/python.exe check_calendar.py --poll-seconds 60`

Useful options:

- `--window-minutes 120`
- `--trigger-before-minutes 2`
- `--calendar primary`
- `--client-secret <path>`
- `--token-file <path>`

## Output

The script prints events with start times and a Meet URL when it can find one (from `hangoutLink`, `conferenceData`, or `location/description`).
If an event is starting soon (within `--trigger-before-minutes`) it prints `TRIGGER:` as a placeholder for your future "join meet" bot.
