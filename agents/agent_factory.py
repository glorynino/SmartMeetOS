from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Generic, Iterable, TypeVar


TContext = TypeVar("TContext")


@dataclass(frozen=True)
class CreatedAgent(Generic[TContext]):
    """Tiny wrapper to mirror a `create_agent(...)` style.

    This is intentionally lightweight: in this codebase we use LangChain
    tool-calling by binding tools to an LLM and then driving a tool-call loop.

    - `llm` is the bound model (`model.bind_tools([...])`).
    - `system_prompt` is stored so call sites can build messages consistently.
    - `context_schema` is optional; you can validate/shape context before building prompts.
    """

    llm: Any
    system_prompt: str
    tools: list[Any]
    context_schema: Any | None = None


def create_agent(
    *,
    model: Any,
    system_prompt: str,
    tools: Iterable[Any],
    context_schema: Any | None = None,
) -> CreatedAgent[Any]:
    """Create a LangChain tool-calling agent wrapper.

    This mirrors the style:
        agent = create_agent(model=model, system_prompt=..., tools=[...])

    We intentionally do not implement a separate "agent executor" abstraction here;
    each node controls its own tool-call loop (so it can enforce required tool calls
    and handle DB writes safely).
    """

    tools_list = list(tools)
    bound = model.bind_tools(tools_list)
    return CreatedAgent(llm=bound, system_prompt=system_prompt, tools=tools_list, context_schema=context_schema)
