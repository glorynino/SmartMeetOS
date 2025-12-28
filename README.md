# SmartMeetOS

SmartMeetOS watches **Google Calendar** for **Google Meet** events and automatically triggers a **Nylas Notetaker** workflow to join meetings, record transcripts, extract insights, and deliver actionable outputs.

It transforms meetings into structured knowledge: documentation, tasks, follow-ups, and calendar actions — delivered via **Notion, Discord, SMS, or email**.

---

## Table of Contents

* [Overview](#smartmeetos)
* [Features](#features)
* [Requirements](#requirements)
* [Installation](#installation)
* [Configuration](#configuration)
* [Project Structure](#project-structure)
* [Usage](#usage)

  * [Calendar Watcher](#1-calendar-watcher-main-process)
* [Architecture](#architecture)

  * [Architecture Diagram](#architecture-1)
  * [Architecture Diagram — Explanation](#architecture-diagram--explanation)
* [Operational Notes](#operational-notes--key-files)

---

## Features

✨ **Core Capabilities**

* 🗓️ **Calendar Monitoring** — Real-time polling of Google Calendar for Meet events
* 📝 **Automatic Transcription** — Nylas Notetaker joins meetings and records transcripts
* 🧠 **AI-Powered Processing** — LLM extraction of facts, decisions, and action items
* 📊 **Semantic Grouping** — Intelligent clustering and conflict resolution
* 📄 **Auto Documentation** — Generate structured meeting notes in Notion
* ⚡ **Task Management** — Automatic follow-ups and task creation
* 💬 **Multi-Channel Delivery** — Discord, SMS, email, or Notion
* 🔄 **Webhook Integration** — Real-time transcript ingestion via Nylas webhooks
* 🗄️ **Meeting History** — SQLAlchemy-backed persistent storage

---

## Requirements

* **Python 3.10+** (3.11+ recommended)
* **Google Calendar OAuth credentials** (JSON file)
* **Nylas API account** (API key + Grant ID)
* **SQLite or PostgreSQL** database

---

## Installation

1. Clone the repository:

```bash
git clone https://github.com/glorynino/SmartMeetOS.git
cd SmartMeetOS
```

2. Create and activate a virtual environment:

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
```

3. Install dependencies:

```bash
pip install -r requirements.txt
```

---

## Configuration

Create a `.env` file at the project root.

### Required Variables

```env
NYLAS_API_KEY=your_nylas_api_key
NYLAS_GRANT_ID=your_grant_id
GOOGLE_CLIENT_SECRET_FILE=secrets/google_credentials.json
NYLAS_WEBHOOK_SECRET=your_webhook_secret
```

### Optional Variables

```env
NYLAS_API_BASE=https://api.us.nylas.com
DISCORD_TOKEN=your_discord_bot_token
SMS_TO_API_KEY=your_sms_api_key
MISTRAL_API_KEY=your_mistral_api_key
DATABASE_URL=sqlite:///smartmeetos.db
```

> Runtime state (tokens, logs, transcripts) is written to `.secrets/` (ignored by git).

---

## Project Structure

```
SmartMeetOS/
├── check_calendar.py          # Main calendar watcher entrypoint
├── requirements.txt
├── agents/                   # Multi-agent orchestration
│   ├── orchestrator.py
│   ├── event_detection_agent.py
│   ├── actions.py
│   ├── documentation.py
│   └── scheduling.py
├── smartmeetos/              # Core application logic
│   ├── calendar/
│   ├── notetaker/
│   │   ├── nylas_notetaker.py
│   │   ├── supervisor.py
│   │   └── failure_codes.py
│   └── webapp/
├── services/                 # External API clients
│   ├── calendar_client.py
│   ├── discord_client.py
│   ├── notion_client.py
│   └── nylas_client.py
├── processing/
│   └── chunker.py
├── database/
│   ├── models.py
│   ├── connection.py
│   └── init_db.py
├── docs/
│   ├── google_calendar_setup.md
│   ├── nylas_notetaker_setup.md
│   └── nylas_webhooks.md
└── .secrets/                 # Runtime state (ignored by git)
```

---

## Usage

### Calendar Watcher (Main Process)

```bash
python check_calendar.py \
  --nylas-notetaker \
  --nylas-grant-id <GRANT_ID> \
  --calendar primary \
  --window-minutes 120 \
  --poll-seconds 15
```

**Options**

* `--nylas-notetaker` — Enable Notetaker
* `--nylas-grant-id` — Grant ID (or env var)
* `--calendar` — Calendar ID (default: primary)
* `--window-minutes` — Look-ahead window
* `--poll-seconds` — Polling interval
* `--dry-run` — No side effects

---



## Architecture

### Architecture Diagram

````mermaid
graph TB

%% =====================
%% Input & Storage
%% =====================
subgraph Input["Input & Storage"]
    A[Nylas Webhook]
    B[Raw Transcript]
    C[(meetings table)]
    A --> B --> C
end

%% =====================
%% Chunking & Parallel Fact Extraction
%% =====================
subgraph Processing["Chunking & Parallel Fact Extraction"]
    D{Processing Pipeline}
    E[Smart Chunker Node]

    F[Chunk 1]
    G[Chunk 2]
    H[...]

    I[Chunk Extractor LLM Node]
    J[Chunk Extractor LLM Node]
    K[...]

    L[(extracted_facts<br/>group_label: NULL)]

    C --> D --> E

    E -->|Splits into| F
    E -->|Splits into| G
    E -->|Splits into| H

    F --> I -->|Creates| L
    G --> J -->|Creates| L
    H --> K -->|Creates| L
end

%% =====================
%% Semantic Grouping & Conflict Resolution
%% =====================
subgraph Semantic["Semantic Grouping & Conflict Resolution"]
    M{Aggregator Router}
    N[Grouping Node]

    O[Aggregator LLM Node<br/>for Group A]
    P[Aggregator LLM Node<br/>for Group B]
    Q[...]

    R[(meeting_inputs table)]

    L --> M
    L -->|Labels facts with group_label| N

    N -->|Queries ungrouped facts<br/>Clusters by context| N

    M -->|Routes each group| O
    M -->|Routes each group| P
    M -->|Routes each group| Q

    O -->|Writes final, resolved context| R
    P -->|Writes final, resolved context| R
    Q -->|Writes final, resolved context| R
end

%% =====================
%% Action Orchestration
%% =====================
subgraph Action["Action Orchestration"]
    S[Supervisor / Router Node]

    T[Documentation Agent]
    U[Action Agent]
    V[Scheduling Agent]

    W[Notion API]
    X[Discord / Twilio API]
    Y[Google Calendar API]

    Z[(document_outputs)]
    AA[(tasks)]
    AB[(calendar_events)]

    R --> S

    S -->|Routes by intent| T
    S -->|Routes by intent| U
    S -->|Routes by intent| V

    T --> W --> Z
    U --> X --> AA
    V --> Y --> AB
end

%% =====================
%% User Delivery
%% =====================
subgraph Delivery["User Delivery"]
    AC[User]
    Z --> AC
    AA --> AC
    AB --> AC
end

````

---

### Architecture Diagram — Explanation

This architecture is designed as a **multi-stage, event-driven pipeline** that transforms raw meeting data into structured knowledge and automated actions.

---

#### 1. Input & Storage

This layer is responsible for **ingesting and persisting raw data**.

* **Nylas Webhook** notifies the system when a meeting transcript is available.
* **Raw Transcript** represents the unprocessed meeting conversation.
* The **`meetings` table** stores transcripts along with metadata (meeting ID, participants, timestamps).

This separation ensures raw data is always preserved and can be reprocessed if needed.

---

#### 2. Processing — Chunking & Parallel Fact Extraction

Meeting transcripts can be long and exceed LLM context limits.

* The **Smart Chunker Node** splits transcripts into smaller, context-aware chunks.
* Each chunk is processed independently by **Extractor LLM Nodes**.
* These nodes extract atomic elements such as:

  * facts
  * decisions
  * action items
* All extracted elements are stored in **`extracted_facts`** with `group_label = NULL`.

This design enables **parallelism**, scalability, and fault tolerance.

---

#### 3. Semantic Grouping & Conflict Resolution

Raw extracted facts are often fragmented or redundant.

* The **Grouping Node** analyzes ungrouped facts and assigns semantic labels based on topic, intent, or participants.
* The **Aggregator Router** routes each labeled group to a dedicated **Aggregator LLM Node**.
* Each aggregator:

  * merges related facts
  * resolves contradictions
  * produces a coherent representation
* Final, resolved context is stored in **`meeting_inputs`**.

This layer converts fragmented information into **consistent, high-level understanding**.

---

#### 4. Action Orchestration

This layer decides **what to do** with the resolved meeting context.

* The **Supervisor / Router** analyzes `meeting_inputs` and infers user intent.
* Based on intent, it dispatches data to specialized agents:

  * **Documentation Agent** → creates structured documents in Notion
  * **Action Agent** → sends notifications or creates tasks (Discord, SMS)
  * **Scheduling Agent** → schedules or updates events in Google Calendar

Outputs are persisted in:

* `document_outputs`
* `tasks`
* `calendar_events`

---

#### 5. Delivery — User-Facing Outputs

The final layer delivers value to the user.

* Documents, tasks, and calendar events are delivered through configured channels.
* All outputs remain stored for auditing, history, and reuse.

This separation allows SmartMeetOS to scale delivery mechanisms without changing core logic.

---

## Operational Notes & Key Files

* Google OAuth: `GOOGLE_CLIENT_SECRET_FILE`
* Webhook verification: `NYLAS_WEBHOOK_SECRET`
* Failure handling: `smartmeetos/notetaker/failure_codes.py`
* Runtime state: `.secrets/`

---

**SmartMeetOS** — From meetings to decisions, automatically.
