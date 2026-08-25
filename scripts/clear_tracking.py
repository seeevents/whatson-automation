#!/usr/bin/env python3
"""
Vide la table Events_Tracking - lance chaque matin AVANT le premier run
(Brique 3), pour que l'equipe voie chaque jour uniquement les events
traites du jour meme.
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import validate_config
from config import settings
from src import airtable_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("whatson.clear_tracking")


def main() -> int:
    missing = validate_config()
    if missing:
        logger.error("Variables d'environnement manquantes: %s", ", ".join(missing))
        return 1

    deleted = airtable_client.delete_all_records(settings.AIRTABLE_TABLE_TRACKING)
    logger.info("Events_Tracking videe: %d ligne(s) supprimee(s)", deleted)
    return 0


if __name__ == "__main__":
    sys.exit(main())
