#!/usr/bin/env python3
"""
Test isole: connexion DIRECTE au serveur MCP GoodBarber (sans passer par
Claude), liste les outils disponibles. Lecture seule, aucune ecriture.
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import validate_config
from src import airtable_client, goodbarber_mcp_client
from config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("whatson.test_mcp_direct")


def _get_goodbarber_access_token() -> str:
    import json as _json

    records = airtable_client.search_records(
        settings.AIRTABLE_TABLE_TOKENS, formula="{Token Label} = 'current'", max_records=1
    )
    if not records:
        raise RuntimeError("Aucun token GoodBarber trouve dans Airtable.")
    token_json = records[0]["fields"].get("fldjX3lvP5GYdDHnU", "{}")
    return _json.loads(token_json).get("access_token", "")


def main() -> int:
    missing = validate_config()
    if missing:
        logger.error("Variables d'environnement manquantes: %s", ", ".join(missing))
        return 1

    logger.info("Recuperation du token GoodBarber depuis Airtable...")
    access_token = _get_goodbarber_access_token()
    if not access_token:
        logger.error("Token GoodBarber vide.")
        return 1

    logger.info("Connexion directe au serveur MCP GoodBarber...")
    try:
        tools = goodbarber_mcp_client.list_tools(access_token)
    except goodbarber_mcp_client.GoodBarberMCPError as exc:
        logger.error("Echec: %s", exc)
        return 1

    print(f"\n=== {len(tools)} outil(s) decouvert(s) via MCP direct ===")
    for tool in tools:
        desc = (tool.get("description") or "")[:80]
        print(f"  - {tool['name']}: {desc}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
