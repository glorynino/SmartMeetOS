from langchain_openai import ChatOpenAI
from calendar_tools import (
    create_calendar_event,
    add_homework_event,
    delete_event,
    reschedule_event
)

SYSTEM_PROMPT = """
Tu es un Scheduling Agent.
Analyse la demande utilisateur.
Choisis les tools appropriés et appelle-les.
"""

TOOLS = [
    create_calendar_event,
    add_homework_event,
    delete_event,
    reschedule_event
]

llm = ChatOpenAI(
    model="gpt-4o-mini",
    temperature=0
).bind_tools(TOOLS)   # ✅ ICI
