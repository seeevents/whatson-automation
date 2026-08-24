#!/usr/bin/env python3
"""
Test isole: publie un enregistrement Airtable de test via le module
Publication DIRECT (sans passer par l'agent Claude pour l'orchestration).
Usage: python scripts/test_publication_direct.py <record_id>
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import validate_config
from src import airtable_client, goodbarber_mcp_client, publication_direct
from config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("whatson.test_publication_direct")


async def _run(client, record):
    return await publication_direct.publish_one_async(client, record)


def main() -> int:
    if len(sys.argv) < 2:
        logger.error("Usage: python scripts/test_publication_direct.py <record_id>")
        return 1

    missing = validate_config()
    if missing:
        logger.error("Variables d'environnement manquantes: %s", ", ".join(missing))
        return 1

    record_id = sys.argv[1]
    logger.warning("MODE TEST - traite uniquement: %s", record_id)

    records = airtable_client.search_records(
        settings.AIRTABLE_TABLE_EVENTS, formula=f"RECORD_ID()='{record_id}'", max_records=1
    )
    if not records:
        logger.error("ID '%s' introuvable.", record_id)
        return 1

    result = goodbarber_mcp_client.run_in_session(lambda client: _run(client, records[0]))
    logger.info("Resultat: %s", result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
