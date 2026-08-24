#!/usr/bin/env python3
"""Test isole: recupere le schema detaille des outils MCP necessaires a
Publication (cms_list_events, cms_create_event, cms_update_event, etc.)
via meta_get_tool_plan. Lecture seule."""
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import goodbarber_mcp_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


async def _get_plans(client):
    tool_names = [
        "cms_list_events",
        "cms_get_event",
        "cms_create_event",
        "cms_update_event",
        "cms_list_event_paragraphs",
        "cms_create_event_paragraph",
        "cms_update_event_paragraph",
        "cms_list_cms_sections",
    ]
    results = {}
    for name in tool_names:
        result = await client.call_tool("meta_get_tool_plan", {"tool_name": name})
        results[name] = goodbarber_mcp_client.parse_tool_result(result)
    return results


def main() -> int:
    plans = goodbarber_mcp_client.run_in_session(_get_plans)
    for name, plan in plans.items():
        print(f"\n{'=' * 70}\n{name}\n{'=' * 70}")
        print(json.dumps(plan, indent=2)[:3000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
