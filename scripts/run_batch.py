#!/usr/bin/env python3
"""
Lance Brique 3 sur les comptes du jour.
Usage: python scripts/run_batch.py [numero_batch]
Si numero_batch (1-8) est fourni, ne traite que ce sous-ensemble (permet
l'execution parallele des 8 batches, comme sur Make). Sans argument,
traite TOUS les comptes du jour sequentiellement.
"""
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import validate_config
from src import accounts, extraction

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("whatson.run_batch")


def main() -> int:
    missing = validate_config()
    if missing:
        logger.error("Variables d'environnement manquantes: %s", ", ".join(missing))
        return 1

    batch_number = sys.argv[1] if len(sys.argv) > 1 else None
    if batch_number:
        logger.info("Mode batch unique: %s", batch_number)

    todays_accounts = accounts.get_todays_accounts(batch_number=batch_number)
    total = len(todays_accounts)
    logger.info("Batch: %d compte(s) a traiter aujourd'hui", total)

    errors = 0
    start = time.time()
    for i, account in enumerate(todays_accounts, start=1):
        try:
            extraction.process_account(account)
        except Exception:
            logger.exception("Echec sur le compte %s - on continue avec le suivant", account.venue_name)
            errors += 1
        logger.info("Progression: %d/%d comptes traites (%d erreur(s))", i, total, errors)

    elapsed = time.time() - start
    logger.info("Batch termine en %.0fs: %d/%d comptes OK, %d erreur(s)", elapsed, total - errors, total, errors)
    return 0


if __name__ == "__main__":
    sys.exit(main())
