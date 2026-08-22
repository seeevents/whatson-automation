#!/usr/bin/env python3
"""
Test isole: connexion DIRECTE au serveur MCP GoodBarber (sans passer par
Claude) via le vrai flux OAuth. Necessite que le bootstrap initial
(scripts/oauth_bootstrap_goodbarber.py) ait deja ete fait au moins une
fois (etat persiste dans Airtable ou fourni via GOODBARBER_MCP_OAUTH_STATE).
Lecture seule, aucune ecriture sur GoodBarber.
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import validate_config
from src import goodbarber_mcp_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("whatson.test_mcp_direct")


def main() -> int:
    missing = validate_config()
    if missing:
        logger.error("Variables d'environnement manquantes: %s", ", ".join(missing))
        return 1

    logger.info("Connexion directe au serveur MCP GoodBarber (OAuth)...")
    try:
        tools = goodbarber_mcp_client.list_tools()
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
