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


async def _get_schemas(client):
    result = await client.list_tools()
    tool_names = {
        "cms_list_events", "cms_get_event", "cms_create_event", "cms_update_event",
        "cms_list_event_paragraphs", "cms_create_event_paragraph", "cms_update_event_paragraph",
    }
    return {t.name: t.input_schema for t in result.tools if t.name in tool_names}


def main() -> int:
    schemas = goodbarber_mcp_client.run_in_session(_get_schemas)
    for name, schema in schemas.items():
        print(f"\n{'=' * 70}\n{name} - SCHEMA COMPLET\n{'=' * 70}")
        print(json.dumps(schema, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
