# Meeting joining & reliability behavior

This repo implements a **Google Calendar poller** that triggers **Nylas Notetaker** to join and record Google Meet links.

The design goal is: **run unsupervised** and still behave predictably when meetings start late, lobbies exist, the bot disconnects, or meetings overlap.

## Components (what runs)

- **Calendar ingestion**: [smartmeetos/calendar/google_calendar.py](../smartmeetos/calendar/google_calendar.py)

  - Uses Google OAuth (token in `.secrets/google_token.json`) to list upcoming events.
  - Extracts Meet links from `hangoutLink`, `conferenceData`, `location`, or `description`.

- **Scheduler / trigger**: [check_calendar.py](../check_calendar.py)

  - Polls on a fixed interval (`--poll-seconds`).
  - Prints events + detects which meetings are eligible to be handled.
  - Enforces **single active meeting** (no parallel joins).
  - Starts the supervisor which blocks until the meeting ends or fails.

- **Nylas API**

  - Create Notetaker: [smartmeetos/notetaker/nylas_notetaker.py](../smartmeetos/notetaker/nylas_notetaker.py)
  - Status/history: [smartmeetos/notetaker/nylas_history.py](../smartmeetos/notetaker/nylas_history.py)
  - Media links + downloads: [smartmeetos/notetaker/nylas_media.py](../smartmeetos/notetaker/nylas_media.py)

- **Reliability supervisor**: [smartmeetos/notetaker/supervisor.py](../smartmeetos/notetaker/supervisor.py)
  - Implements the failure-handling policies described below.

## How joining works (end-to-end)

1. `check_calendar.py` lists upcoming events from Google Calendar.
2. For each event, it computes an eligibility window:
   - **For Notetaker joining (mandatory policy)**: from **start − 2 minutes** to **start + 15 minutes**.
3. If multiple events are eligible in the same poll:
   - The earliest start is selected.
   - All other eligible events are skipped with: `SKIPPED_OVERLAP_CONFLICT`.
4. The supervisor creates a Notetaker and then polls its `/history` to determine the bot’s meeting state.

## Reliability policies implemented

### 1) Join timing window (mandatory)

- Attempts allowed between:
  - **T_start − 2 minutes** and **T_start + 15 minutes**
- If creation/join does not succeed in that window:
  - Failure: `JOIN_TIMEOUT`
- Retry cadence:
  - Create attempt every **30–60 seconds**

### 2) Meeting does not exist yet / host not joined

If the Notetaker reports an entry failure early (e.g., room not ready):

- Do **not** fail immediately
- Continue retries within the join window

### 3) Waiting room / admission failure

If the bot is stuck in the lobby:

- Max waiting-room time: **5 minutes**
- Failure: `WAITING_ROOM_TIMEOUT`

### 4) Unexpected disconnection (mandatory)

If the bot was recording and then gets disconnected:

- Attempt rejoin every **30 seconds**
- Max reconnection duration: **5 minutes**
- Rejoin is implemented by creating a **new Notetaker instance** (new `notetaker_id`).
- Failure: `DISCONNECTED_TIMEOUT`

### 5) Bot explicitly removed (best-effort)

If history indicates removal/kick:

- Stop retries immediately
- Failure: `BOT_REMOVED`

### 6) Overlapping meetings (mandatory)

Policy: only one meeting may be active.

- If another meeting becomes eligible while one is being handled:
  - It is skipped
  - Failure: `SKIPPED_OVERLAP_CONFLICT`

### 7) Meeting overruns (mandatory)

Max allowed runtime:

- `scheduled_duration + 30 minutes`
  If exceeded:
- Supervisor stops and returns: `MAX_DURATION_EXCEEDED`

### 8) Meeting end detection (partial)

Spec requested “end when any 2 of these occur”:

- Meeting API reports ended
- Bot alone > 60 seconds
- No audio detected > 5 minutes
- Event end + 15 min grace exceeded

Current implementation can only observe:

- **API ended** (via Nylas history `meeting_state`)
- **End grace exceeded**
- **Media available** (transcript/recording URL available)

So we end when **2 of these observable signals** are present.

### 9) Transcript safety (partial but robust)

True incremental transcripts are not available from the current endpoints.
What we do instead:

- Persist media references per Notetaker attempt (never overwrite)
- Best-effort download transcript content once it’s available
- Reconnect attempts create a new Notetaker, so data is kept separate

Files written:

- `.secrets/transcripts/<event>__<start>__<notetaker_id>.media.json`
- `.secrets/transcripts/<event>__<start>__<notetaker_id>.transcript.json`

## Outputs & observability

- Trigger dedupe state (prevents duplicate handling):

  - `.secrets/trigger_state.json`

- Structured run results:

  - `.secrets/meeting_results.json`

- Status CLI:

  - `python .\check_notetaker_status.py --grant-id <GRANT> --notetaker-id <ID> --show-events 10`

- Transcript printer:
  - `python .\print_notetaker_transcript.py --grant-id <GRANT> --notetaker-id <ID> --wait-seconds 600`

## Operational notes

- The supervisor is **blocking by design**. While it’s supervising a meeting, the poll loop doesn’t start additional meetings.
- If you want different overlap policy (queue instead of skip), that is a redesign and not implemented.
- Nylas and Meet environments vary. If you share a sample `--show-events 10` output (no secrets), we can tune the status parsing conservatively.
