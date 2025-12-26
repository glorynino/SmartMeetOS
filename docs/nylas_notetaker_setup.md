# Nylas Notetaker integration (CLI)

This repo can trigger **Nylas Notetaker** when a Google Calendar event with a Google Meet link becomes due.

## Prerequisites

- A Nylas v3 account + application
- A Nylas API key (Contract plans only for Notetaker)
- (Optional) A `grant_id` if you want grant-scoped Notetakers

## Configuration

Set environment variables:

- `NYLAS_API_KEY`: your Nylas API key
- (Optional) `NYLAS_API_BASE`: defaults to `https://api.us.nylas.com`

## Run

Create a Notetaker when a meeting is triggered:

- `python check_calendar.py --calendar primary --window-minutes 120 --poll-seconds 30 --trigger-before-minutes 2 --trigger-after-start-minutes 10 --nylas-notetaker`

Grant-based Notetaker (calendar sync compatible):

- `python check_calendar.py --calendar primary --poll-seconds 30 --nylas-notetaker --nylas-grant-id <NYLAS_GRANT_ID>`

Notes:

- The CLI only creates a Notetaker **once per event occurrence** (it de-dupes by event id + start time).
- Notetaker creation uses the meeting URL we extract from the calendar event (`meeting_link`).
- If your Google Meet requires admitting guests, you may need to approve the Notetaker when it tries to join.
