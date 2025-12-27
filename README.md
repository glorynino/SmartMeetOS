# SmartMeetOS

**SmartMeetOS** is an agentic system that turns meetings into actions by transcribing conversations, reasoning over decisions, and autonomously executing follow-ups using connected tools.

---

## 🧠 What it does

- Automatically joins scheduled meetings
- Transcribes audio and captures chat/messages
- Reasons over discussions to extract decisions, action items, and deadlines
- Executes actions autonomously (tasks, notifications, calendar updates)
- Tracks outcomes and prepares concise summaries for the next meeting

## Reliability / joining behavior

See [docs/meeting_joining_reliability.md](docs/meeting_joining_reliability.md) for the implemented join windows, retries, overlap behavior, failure codes, and persisted outputs.

## Nylas webhooks (recommended for transcript delivery)

Nylas can push `notetaker.media` events (processing/available) so you can download transcripts as soon as they are ready without blocking the next meeting.

- Setup guide: [docs/nylas_webhooks.md](docs/nylas_webhooks.md)
- Local receiver: [webhook_receiver.py](webhook_receiver.py)

---

## 🏗️ Architecture Overview

```mermaid
flowchart TB

%% =========================
%% Monitoring & Trigger
%% =========================
subgraph MT["Monitoring & Trigger"]
    GC["Google Calendar Monitor"]
    MST["Meeting Start Trigger"]
    GC --> MST
end

MST -->|Meeting URL & Time| NY["Nylas API<br/>Joins & Records"]
NY --> PM["Post-Meeting:<br/>Transcript & Data"]

%% =========================
%% LangGraph Core
%% =========================
subgraph LG["LangGraph Core"]
    SA["Supervisor Agent"]

    %% Documentation flow
    DA["Documentation Agent"]
    NOTION_DOC["Tool: Notion API"]
    DIAG["Tool: Diagram Generator<br/>(e.g. Mermaid)"]
    CRS["Compile Rich Summary"]

    %% Action flow
    AA["Action Agent"]
    PUSH["Tool: Push Notification<br/>(Twilio / Slack)"]
    NOTION_ACT["Tool: Notion API"]
    ALERT["Send Immediate Alerts"]

    %% Scheduling flow
    SCHED["Scheduling Agent"]
    GC_API["Tool: Google Calendar API"]
    REM["Tool: Reminders via<br/>Google Calendar"]
    SREM["Schedule & Set Reminders"]

    SA -->|Content for Documentation| DA
    SA -->|Urgent User Actions| AA
    SA -->|Future Events & Dates| SCHED

    DA --> NOTION_DOC
    DA --> DIAG
    NOTION_DOC --> CRS
    DIAG --> CRS

    AA --> PUSH
    AA --> NOTION_ACT
    PUSH --> ALERT
    NOTION_ACT --> ALERT

    SCHED --> GC_API
    SCHED --> REM
    GC_API --> SREM
    REM --> SREM
end

PM --> SA

%% =========================
%% User Delivery Hub
%% =========================
subgraph UD["User Delivery Hub"]
    HUB["User Delivery Hub"]
    NP["Notion Page"]
    PN["Push Notification"]
    CE["Calendar Event"]

    HUB --> NP
    HUB --> PN
    HUB --> CE
end

CRS --> HUB
ALERT --> HUB
SREM --> HUB
```
