from calendar_tools import (
    create_calendar_event,
    add_homework_event,
    delete_event,
    reschedule_event
)
from agent import llm_with_tools, SYSTEM_PROMPT
from langchain_core.messages import SystemMessage, HumanMessage

PROMPT = """
décale le meeting intitulé Cours d’algèbre de 10:00 à 12:00,
"""

response = llm_with_tools.invoke([
    SystemMessage(content=SYSTEM_PROMPT),
    HumanMessage(content=PROMPT)
])
for tool_call in response.tool_calls:
    tool_name = tool_call["name"]
    tool_args = tool_call["args"]

    # Mapper le nom vers la vraie fonction
    tool_map = {
        "create_calendar_event": create_calendar_event,
        "add_homework_event": add_homework_event,
        "delete_event": delete_event,
        "reschedule_event": reschedule_event,
    }

    result = tool_map[tool_name].invoke(tool_args)
    print("✅ TOOL EXECUTED:", result)
