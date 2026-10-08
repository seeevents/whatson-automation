#!/usr/bin/env python3
"""Passage hebdomadaire Google Events. Usage: python scripts/run_google_events.py"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import validate_config
from src import google_events

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("whatson.run_google_events")


def main() -> int:
    missing = validate_config()
    if missing:
        logger.error("Variables d'environnement manquantes: %s", ", ".join(missing))
        return 1
    try:
        stats = google_events.run()
    except Exception:
        logger.exception("Echec Google Events")
        return 1
    logger.info("Resume: %s", stats)
    return 0


if __name__ == "__main__":
    sys.exit(main())
