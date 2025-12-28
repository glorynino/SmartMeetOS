from langchain_openai import ChatOpenAI
from calendar_tools import (
    create_calendar_event,
    add_homework_event,
    delete_event,
    reschedule_event
)

SYSTEM_PROMPT = """
Tu es un Scheduling Agent.
Analyse la demande utilisateur et appelle les tools appropriés
pour gérer Google Calendar.
"""

llm = ChatOpenAI(
    model="gpt-4o-mini",
    temperature=0
)

TOOLS = [
    create_calendar_event,
    add_homework_event,
    delete_event,
    reschedule_event
]

llm_with_tools = llm.bind_tools(TOOLS)
