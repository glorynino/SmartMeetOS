# SmartMeetOS

SmartMeetOS watches Google Calendar for Google Meet events and triggers a Nylas Notetaker workflow to join meetings and save transcripts.

## Requirements

- Python 3.10+ recommended
- Google Calendar OAuth client JSON in `secrets/` (ignored by git)
- Nylas API key + grant id for Notetaker

Install dependencies:

```bash
pip install -r requirements.txt
```

## Run (calendar watcher)

Use `check_calendar.py` as the main entrypoint:

```bash
python check_calendar.py --nylas-notetaker --nylas-grant-id <GRANT_ID>
```

Environment variables supported:

- `NYLAS_API_KEY`
- `NYLAS_API_BASE` (optional)

Runtime state (tokens, history logs, transcripts) is written under `.secrets/` (ignored by git).
