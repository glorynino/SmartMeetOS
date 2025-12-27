from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
import os
import pickle

# Scope Google Calendar (accès complet)
SCOPES = ["https://www.googleapis.com/auth/calendar"]

def get_calendar_service():
    creds = None

    # Charger le token s'il existe déjà
    if os.path.exists("token.pickle"):
        with open("token.pickle", "rb") as token:
            creds = pickle.load(token)

    # Si pas valide → authentification
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                "credentials.json",
                SCOPES
            )
            creds = flow.run_local_server(port=0)

        # Sauvegarde du token
        with open("token.pickle", "wb") as token:
            pickle.dump(creds, token)

    return build("calendar", "v3", credentials=creds)


# ====== MAIN ======
service = get_calendar_service()

event = {
    "summary": "Cours d’algèbre",
    "description": "Cours avec lien Google Meet",
    "start": {
        "dateTime": "2025-01-15T09:00:00",
        "timeZone": "Africa/Algiers",
    },
    "end": {
        "dateTime": "2025-01-15T11:00:00",
        "timeZone": "Africa/Algiers",
    },
    "conferenceData": {
        "createRequest": {
            "requestId": "alg-20250115-001"
        }
    },
    "reminders": {
        "useDefault": False,
        "overrides": [
            {"method": "popup", "minutes": 30}
        ],
    },
}

created_event = service.events().insert(
    calendarId="primary",
    body=event,
    conferenceDataVersion=1
).execute()

print("✅ Événement créé avec succès !")
print("📅 Lien Calendar :", created_event.get("htmlLink"))

# Afficher le lien Google Meet généré
meet_link = created_event.get("conferenceData", {}) \
    .get("entryPoints", [{}])[0] \
    .get("uri")

if meet_link:
    print("🎥 Lien Google Meet :", meet_link)
