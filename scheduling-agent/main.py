from agent import llm, SYSTEM_PROMPT, TOOLS
from langchain_core.messages import SystemMessage, HumanMessage

PROMPT = """
Crée un meeting intitulé Cours d’algèbre le 28 janvier 2025 de 09:00 à 11:00,
puis décale-le de 10:00 à 12:00,
et ajoute un devoir d’algèbre pour le 30 janvier à 18:00.
"""

messages = [
    SystemMessage(content=SYSTEM_PROMPT),
    HumanMessage(content=PROMPT)
]

response = llm.invoke(messages)

tool_map = {tool.name: tool for tool in TOOLS}
last_event_id = None

if response.tool_calls:
    for call in response.tool_calls:
        tool_name = call["name"]
        args = call["args"]

        if tool_name == "reschedule_event":
            args["event_id"] = last_event_id

        print(f"\n➡️ TOOL: {tool_name}")
        print("ARGS:", args)

        result = tool_map[tool_name].invoke(args)
        print("✅ RESULT:", result)

        if tool_name == "create_calendar_event":
            last_event_id = result["event_id"]
else:
    print("ℹ️ Aucun tool appelé")
