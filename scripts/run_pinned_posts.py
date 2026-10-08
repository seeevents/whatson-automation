#!/usr/bin/env python3
"""Passage hebdomadaire sur les posts epingles. Usage: python scripts/run_pinned_posts.py [numero_batch]"""
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import validate_config
from src import accounts, extraction

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("whatson.run_pinned_posts")


def main() -> int:
    missing = validate_config()
    if missing:
        logger.error("Variables d'environnement manquantes: %s", ", ".join(missing))
        return 1
    batch_number = sys.argv[1] if len(sys.argv) > 1 else None
    todays = accounts.get_todays_accounts(batch_number=batch_number, all_weekdays=True)
    total, errors, start = len(todays), 0, time.time()
    logger.info("Passage epingles: %d compte(s)", total)
    for i, account in enumerate(todays, start=1):
        try:
            extraction.process_account_pinned(account)
        except Exception:
            logger.exception("Echec sur %s - on continue", account.venue_name)
            errors += 1
        logger.info("Progression: %d/%d (%d erreur(s))", i, total, errors)
    logger.info("Termine en %.0fs: %d/%d OK", time.time() - start, total - errors, total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
