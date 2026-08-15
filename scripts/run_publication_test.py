#!/usr/bin/env python3
"""
Lance la Publication en mode TEST : ne touche QUE les enregistrements dont
l'ID est passé en argument, jamais la vraie file 'Validé' de production.

Usage: python scripts/run_publication_test.py rec1234 rec5678
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import validate_config
from src import publication

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("whatson.run_publication_test")


def main() -> int:
    if len(sys.argv) < 2:
        logger.error("Usage: python scripts/run_publication_test.py <record_id> [record_id...]")
        return 1

    missing = validate_config()
    if missing:
        logger.error("Variables d'environnement manquantes: %s", ", ".join(missing))
        return 1

    record_ids = sys.argv[1:]
    logger.warning("MODE TEST - traite uniquement: %s", record_ids)

    try:
        summary = publication.run(dry_run_record_ids=record_ids)
    except Exception:
        logger.exception("Echec fatal de la Publication (test)")
        return 1

    logger.info("Résumé final: %s", summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
