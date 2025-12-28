from __future__ import annotations

# Matches the architecture diagram:
# "Aggregator Router" (routes each fact group to the right aggregator call)

from collections import defaultdict
from typing import Any

from agents.grouping_node import get_default_group_label


def route_facts_by_group_label(
    facts: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    default_label = get_default_group_label()
    for f in facts:
        gl = str(f.get("group_label") or default_label)
        groups[gl].append(f)
    return dict(groups)
