#!/usr/bin/env python3
"""Lance la Publication DIRECTE (sans agent Claude pour l'orchestration).
Usage: python scripts/run_publication_direct.py"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import validate_config
from src import publication_direct

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("whatson.run_publication_direct")


def main() -> int:
    missing = validate_config()
    if missing:
        logger.error("Variables d'environnement manquantes: %s", ", ".join(missing))
        return 1

    try:
        summary = publication_direct.run()
    except Exception:
        logger.exception("Echec fatal de la Publication Direct")
        return 1

    logger.info("Résumé final: %s", summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
