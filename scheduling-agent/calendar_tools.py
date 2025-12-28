from langchain_core.tools import tool
from google_calendar_service import get_calendar_service

service = get_calendar_service()


@tool
def create_calendar_event(
    title: str,
    start_time: str,
    end_time: str,
    timezone: str = "Africa/Algiers"
):
    """Créer un meeting ou événement dans Google Calendar."""
    event = {
        "summary": title,
        "start": {"dateTime": start_time, "timeZone": timezone},
        "end": {"dateTime": end_time, "timeZone": timezone},
    }

    created = service.events().insert(
        calendarId="primary",
        body=event
    ).execute()

    return {
        "event_id": created["id"],
        "link": created["htmlLink"]
    }


@tool
def add_homework_event(
    subject: str,
    due_date: str,
    description: str = ""
):
    """Ajouter un devoir (homework) dans Google Calendar."""
    event = {
        "summary": f"📚 Devoir - {subject}",
        "description": description,
        "start": {"dateTime": due_date, "timeZone": "Africa/Algiers"},
        "end": {"dateTime": due_date, "timeZone": "Africa/Algiers"},
    }

    created = service.events().insert(
        calendarId="primary",
        body=event
    ).execute()

    return {"event_id": created["id"]}


@tool
def delete_event(event_id: str):
    """Supprimer un événement Google Calendar."""
    service.events().delete(
        calendarId="primary",
        eventId=event_id
    ).execute()

    return {"status": "deleted"}


@tool
def reschedule_event(
    event_id: str,
    new_start: str,
    new_end: str,
    timezone: str = "Africa/Algiers"
):
    """
    Décale un événement Google Calendar existant.
    """
    service = get_calendar_service()

    event = service.events().get(
        calendarId="primary",
        eventId=event_id
    ).execute()

    event["start"] = {
        "dateTime": new_start,
        "timeZone": timezone
    }
    event["end"] = {
        "dateTime": new_end,
        "timeZone": timezone
    }

    updated = service.events().update(
        calendarId="primary",
        eventId=event_id,
        body=event
    ).execute()

    return {
        "status": "rescheduled",
        "event_id": updated["id"],
        "link": updated["htmlLink"]
    }
