from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
import json
from datetime import datetime

# -----------------------------
# Initialisation du LLM
# -----------------------------
llm = ChatOpenAI(
    model="gpt-5-nano",
    temperature=0
)

# -----------------------------
# Prompt système du Scheduling Agent
# -----------------------------
SYSTEM_PROMPT = """
Tu es un Scheduling Agent.

Ta mission :
- extraire les informations nécessaires pour créer un événement Google Calendar
- ne RIEN inventer
- si une information est absente, mets null

Réponds STRICTEMENT en JSON valide avec ce format :

{
  "title": "",
  "start_time": "",
  "end_time": "",
  "timezone": "Africa/Algiers",
  "meet_link": null,
  "reminders": []
}

Les dates doivent être au format ISO 8601.
"""

# -----------------------------
# INPUT MANUEL (simulation Supervisor)
# -----------------------------
supervisor_input = """
Cours d’algèbre demain de 9h à 11h.
Lien : https://meet.google.com/abc-defg-hij
Rappel 30 minutes avant.
"""

print("🧠 Input envoyé au Scheduling Agent :")
print(supervisor_input)
print("-" * 50)

# -----------------------------
# Appel du Scheduling Agent
# -----------------------------
response = llm.invoke([
    SystemMessage(content=SYSTEM_PROMPT),
    HumanMessage(content=supervisor_input)
])

# -----------------------------
# Parsing JSON
# -----------------------------
try:
    event_data = json.loads(response.content)
except json.JSONDecodeError:
    print("❌ Erreur : le modèle n’a pas renvoyé un JSON valide")
    print(response.content)
    exit()

# -----------------------------
# Résultat final
# -----------------------------
print("📅 Données extraites pour Google Calendar :")
print(json.dumps(event_data, indent=2, ensure_ascii=False))
