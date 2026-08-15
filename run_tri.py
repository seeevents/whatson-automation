#!/usr/bin/env python3
"""Lance le Tri automatisé. Usage: python scripts/run_tri.py"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import validate_config
from src import tri

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("whatson.run_tri")


def main() -> int:
    missing = validate_config()
    if missing:
        logger.error("Variables d'environnement manquantes: %s", ", ".join(missing))
        return 1

    try:
        summary = tri.run()
    except Exception:
        logger.exception("Echec fatal du Tri")
        return 1

    logger.info("Résumé final: %s", summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
